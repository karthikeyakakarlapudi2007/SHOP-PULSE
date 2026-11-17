"""
Document preparation API: capture session -> pages -> manual correction -> PDF -> extraction.

Most tests switch the optional OCR evidence off for speed; test_extract_* runs the real
existing OCR engine end to end and is skipped when it is not installed.
"""

import dataclasses
import io

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from api.deps import get_db
from api.routes import document_prep as dp_routes
from db.session import Base
from doc_prep_dataset import build_dataset
from main import app
from services.document_prep import pipeline as dp_pipeline
from services.document_prep.config import default_config
from services.document_prep.ocr_scoring import ocr_engine_available
from services.document_prep.session_store import SessionStore

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)
API = "/api/v1/document-prep"


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    cfg = dataclasses.replace(default_config, storage_dir=tmp_path / "store", archive_dir=tmp_path / "archive")
    monkeypatch.setattr(dp_routes, "store", SessionStore(cfg))
    yield tmp_path
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def no_ocr(monkeypatch):
    monkeypatch.setattr(dp_pipeline, "ocr_engine_available", lambda: False)


def auth(email="prep@example.com", shop=True):
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    if shop:
        client.post("/api/v1/shops", json={"shop_name": "Kirana Mart", "owner_name": "Ramesh",
                                           "business_type": "Grocery/Kirana", "location": "Bengaluru"}, headers=headers)
    return headers


def jpeg(img, quality=92):
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return enc.tobytes()


@pytest.fixture(scope="module")
def data():
    return build_dataset()


def add_page(sid, headers, img, name="page.jpg"):
    return client.post(f"{API}/sessions/{sid}/pages", files={"file": (name, jpeg(img), "image/jpeg")}, headers=headers)


def test_requires_authentication():
    assert client.post(f"{API}/sessions").status_code == 401
    assert client.get(f"{API}/sessions/{'0' * 32}").status_code == 401


def test_full_review_flow(no_ocr, data):
    h = auth()
    sid = client.post(f"{API}/sessions", headers=h).json()["session_id"]
    r1 = add_page(sid, h, data["04_rotated_180"].pages[0])
    assert r1.status_code == 201, r1.text
    p1 = r1.json()
    assert p1["auto_rotation_cw"] == 180
    assert p1["quality_before"]["grade"] in ("EXCELLENT", "GOOD", "NEEDS_ENHANCEMENT")
    assert "original" in [v["name"] for v in p1["variants"]]
    p2 = add_page(sid, h, data["12_multi_page"].pages[1]).json()
    assert p2["auto_rotation_cw"] == 270

    # Manual rotation: right, 180, reset
    assert client.patch(f"{API}/sessions/{sid}/pages/{p1['page_id']}", json={"rotate_by": 90}, headers=h).json()["manual_rotation"] == 90
    assert client.patch(f"{API}/sessions/{sid}/pages/{p1['page_id']}", json={"rotate_by": 180}, headers=h).json()["manual_rotation"] == 270
    assert client.patch(f"{API}/sessions/{sid}/pages/{p1['page_id']}", json={"rotation": 0}, headers=h).json()["manual_rotation"] == 0
    assert client.patch(f"{API}/sessions/{sid}/pages/{p1['page_id']}", json={"rotation": 45}, headers=h).status_code == 422
    # Version choice
    r = client.patch(f"{API}/sessions/{sid}/pages/{p1['page_id']}", json={"selected_variant": "original"}, headers=h)
    assert r.json()["selected_variant"] == "original"

    # Previews (private, rotated server-side)
    img = client.get(f"{API}/sessions/{sid}/pages/{p2['page_id']}/image?variant=corrected&size=thumb", headers=h)
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert "no-store" in img.headers["cache-control"]
    orig = client.get(f"{API}/sessions/{sid}/pages/{p1['page_id']}/original", headers=h)
    assert orig.content == jpeg(data["04_rotated_180"].pages[0])  # byte-for-byte original

    # Reorder + PDF preserves order
    order = client.put(f"{API}/sessions/{sid}/order", json={"page_ids": [p2["page_id"], p1["page_id"]]}, headers=h).json()
    assert [p["page_id"] for p in order["pages"]] == [p2["page_id"], p1["page_id"]]
    pdf = client.post(f"{API}/sessions/{sid}/pdf", json={"source": "processed"}, headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["x-page-count"] == "2"
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf.content)
    assert len(doc) == 2
    # page 1 is the corrected sideways page (portrait), page 2 the selected original (portrait photo)
    assert doc[0].get_height() > doc[0].get_width()

    # Reprocess without automatic corrections keeps the original and resets rotation
    re = client.post(f"{API}/sessions/{sid}/pages/{p2['page_id']}/reprocess",
                     json={"auto_orientation": False, "perspective": False}, headers=h).json()
    assert re["auto_rotation_cw"] == 0 and re["index"] == 0

    # Delete a page
    left = client.delete(f"{API}/sessions/{sid}/pages/{p1['page_id']}", headers=h).json()
    assert left["page_count"] == 1
    assert client.delete(f"{API}/sessions/{sid}", headers=h).status_code == 204
    assert client.get(f"{API}/sessions/{sid}", headers=h).status_code == 404


def test_isolation_and_bad_ids(no_ocr, data):
    h1 = auth("one@example.com")
    h2 = auth("two@example.com")
    sid = client.post(f"{API}/sessions", headers=h1).json()["session_id"]
    pid = add_page(sid, h1, data["01_clear_portrait"].pages[0]).json()["page_id"]
    assert client.get(f"{API}/sessions/{sid}", headers=h2).status_code == 404
    assert client.get(f"{API}/sessions/{sid}/pages/{pid}/original", headers=h2).status_code == 404
    assert client.patch(f"{API}/sessions/{sid}/pages/{pid}", json={"rotation": 90}, headers=h2).status_code == 404
    for bad in ("..%2F..%2Fsecret", "nothex" * 4, sid[:-1]):
        assert client.get(f"{API}/sessions/{bad}", headers=h1).status_code == 404
    assert client.get(f"{API}/sessions/{sid}/pages/{pid}/image?variant=../../x", headers=h1).status_code == 422


@pytest.mark.parametrize("payload,name,status", [
    (b"%PDF-1.4\n...", "invoice.pdf", 415),
    (b"just text", "notes.txt", 415),
    (b"GIF89a....", "anim.gif", 415),
    (b"\xff\xd8\xff\xe0broken jpeg", "broken.jpg", 422),
])
def test_invalid_uploads_rejected(no_ocr, payload, name, status):
    h = auth()
    sid = client.post(f"{API}/sessions", headers=h).json()["session_id"]
    r = client.post(f"{API}/sessions/{sid}/pages", files={"file": (name, payload, "image/jpeg")}, headers=h)
    assert r.status_code == status, r.text
    assert client.get(f"{API}/sessions/{sid}", headers=h).json()["page_count"] == 0


def test_page_limit_enforced(no_ocr, monkeypatch, tmp_path):
    cfg = dataclasses.replace(default_config, storage_dir=tmp_path / "s2", max_pages_per_session=1)
    monkeypatch.setattr(dp_routes, "store", SessionStore(cfg))
    h = auth()
    sid = client.post(f"{API}/sessions", headers=h).json()["session_id"]
    page = np.full((900, 700, 3), 245, np.uint8)
    cv2.putText(page, "INVOICE 123.45", (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
    assert add_page(sid, h, page).status_code == 201
    assert add_page(sid, h, page).status_code == 400


def test_extract_requires_shop_and_pages(no_ocr):
    h = auth(shop=False)
    sid = client.post(f"{API}/sessions", headers=h).json()["session_id"]
    assert client.post(f"{API}/sessions/{sid}/extract", json={"source": "processed"}, headers=h).status_code == 400
    h2 = auth("withshop@example.com")
    sid2 = client.post(f"{API}/sessions", headers=h2).json()["session_id"]
    assert client.post(f"{API}/sessions/{sid2}/extract", json={"source": "processed"}, headers=h2).status_code == 400


@pytest.mark.skipif(not ocr_engine_available(), reason="OCR engine (node + tesseract.js) not installed")
def test_extract_multi_page_through_existing_ocr(data, setup):
    """Real end-to-end: an upside-down page and a sideways page go through the unchanged
    invoice extraction and every line item, decimal and page order survives."""
    h = auth()
    sid = client.post(f"{API}/sessions", headers=h).json()["session_id"]
    assert add_page(sid, h, data["04_rotated_180"].pages[0]).status_code == 201
    assert add_page(sid, h, data["12_multi_page"].pages[1]).status_code == 201
    res = client.post(f"{API}/sessions/{sid}/extract", json={"source": "processed"}, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    items = body["extraction"]["items"]
    names = [i["product_name"].lower() for i in items]
    # Page order preserved: page-1 products come before page-2 products
    assert names.index("aashirvaad atta 5kg") < names.index("maggi noodles 70g")
    by_name = {i["product_name"].lower(): i for i in items}
    assert by_name["eno fruit salt 5g"]["purchase_price"] == pytest.approx(0.85)
    assert by_name["toor dal loose"]["quantity"] == pytest.approx(2.5)
    assert by_name["brooke bond red label 250g"]["line_total"] == pytest.approx(673.5)
    assert len(items) >= 10
    prep = body["preparation"]
    assert prep["source"] == "processed" and prep["page_count"] == 2 and prep["archived"]
    archived = list((setup / "archive").rglob("*"))
    names_on_disk = {p.name for p in archived}
    assert {"page01_original.jpg", "page02_original.jpg", "submitted_to_ocr.pdf", "manifest.json"} <= names_on_disk

    # Fallback: the untouched originals can still be sent to OCR
    fallback = client.post(f"{API}/sessions/{sid}/extract", json={"source": "original"}, headers=h)
    assert fallback.status_code == 200
    assert fallback.json()["preparation"]["source"] == "original"


def test_heic_upload_preview_and_original_fallback(no_ocr, monkeypatch):
    from pathlib import Path

    from services.document_prep.loader import heif_supported

    if not heif_supported():
        pytest.skip("HEIF decoder not installed")
    heic = (Path(__file__).resolve().parent / "fixtures" / "heic" / "invoice_exif6.heic").read_bytes()
    h = auth()
    sid = client.post(f"{API}/sessions", headers=h).json()["session_id"]
    r = client.post(f"{API}/sessions/{sid}/pages", files={"file": ("IMG_0001.HEIC", heic, "image/heic")}, headers=h)
    assert r.status_code == 201, r.text
    page = r.json()
    assert page["auto_rotation_cw"] == 0  # orientation came from the file, applied once
    exif_step = next(s for s in page["steps"] if s["step"] == "exif_orientation")
    assert exif_step["details"]["exif_orientation"] == 6
    orig = client.get(f"{API}/sessions/{sid}/pages/{page['page_id']}/original", headers=h)
    assert orig.content == heic and orig.headers["content-type"] == "image/heic"
    assert client.get(f"{API}/sessions/{sid}/pages/{page['page_id']}/image?variant=corrected&size=thumb",
                      headers=h).status_code == 200

    # "Original photos" for a HEIC page are sent as a PDF of the decoded pixels (the existing
    # OCR upload does not accept HEIC); the extraction call itself is replaced here.
    captured = {}

    def fake_extract(file_bytes, filename, db, shop_id):
        captured["name"], captured["head"] = filename, file_bytes[:5]
        from schemas.invoice import InvoiceExtractResponse
        return InvoiceExtractResponse(id="inv_x")

    monkeypatch.setattr(dp_routes.invoice_service, "extract_invoice_from_bytes", fake_extract)
    res = client.post(f"{API}/sessions/{sid}/extract", json={"source": "original"}, headers=h)
    assert res.status_code == 200, res.text
    assert captured == {"name": "invoice-scan.pdf", "head": b"%PDF-"}
