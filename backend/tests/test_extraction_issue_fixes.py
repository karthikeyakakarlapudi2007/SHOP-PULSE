"""
Regression tests for three extraction defects found while validating the invoice photo
preparation layer (one test group per root cause; see docs/document-prep/VALIDATION_REPORT.md).

1. PDF raw-stream fallback read inflated *image* data as text (image-only PDFs reported as
   "digital" with garbage words).
2. Supplier name became an "Invoice No" field line when OCR split a large title into one-word
   lines and clipped "In" from "Invoice No:".
3. A decimal point misread by OCR ("58.75" -> "58575") produced a rate 1000x too high with no
   hint for the reviewer. The value must stay as read; a correction is only *suggested*.
"""

import io
import uuid
import zlib
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from api.deps import get_db
from db.session import Base
from main import app
from services import invoice as invoice_service
from services.grocery_ocr.processors.pdf_processor import BasePDFProcessor
from services.grocery_ocr.schemas.invoice import ExtractedInvoice, InvoiceProcessingMetadata
from services.grocery_ocr.schemas.invoice_item import ExtractedInvoiceItem
from services.invoice import extract_metadata, suggest_misread_decimal_rate


# ---------------------------------------------------------------------------------------
# 1. PDF raw-stream fallback
# ---------------------------------------------------------------------------------------


def _pdf(objects):
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


def image_only_pdf_with_operator_bytes() -> bytes:
    """A scanner-style PDF: one Flate image whose pixel bytes happen to contain text operators."""
    w = 256
    payload = b"BT (Fake words from pixel data) Tj ET BT (more fake words appear here too) Tj ET"
    img = np.full((40, w), 255, np.uint8)
    img[10, :len(payload)] = np.frombuffer(payload, np.uint8)
    data = zlib.compress(img.tobytes())
    return _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 61 10] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 30 >>\nstream\nq 61 0 0 10 0 0 cm /Im0 Do Q\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width %d /Height 40 /ColorSpace /DeviceGray /BitsPerComponent 8 "
        b"/Filter /FlateDecode /Length %d >>\nstream\n" % (w, len(data)) + data + b"\nendstream",
    ])


def text_stream_pdf() -> bytes:
    """A simple text PDF whose content stream is Flate-compressed (fallback must still read it)."""
    content = zlib.compress(
        b"BT /F1 12 Tf 50 750 Td (Item Qty Rate Amount) Tj 0 -20 Td (Tata Salt 1kg 20 22.00 440.00) Tj "
        b"0 -20 Td (Maggi Noodles 70g 48 11.00 528.00) Tj ET")
    return _pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream",
    ])


def test_image_pixels_are_not_read_as_digital_text():
    result = BasePDFProcessor().process(image_only_pdf_with_operator_bytes())
    assert result.is_digital is False
    assert result.digital_document is None
    assert result.page_count == 1 and result.pages_rasterized  # goes to OCR instead


def test_real_text_streams_are_still_read_by_the_fallback():
    proc = BasePDFProcessor()
    text = proc._extract_raw_pdf_stream_text(text_stream_pdf())
    assert "Tata Salt 1kg 20 22.00 440.00" in text
    assert "Maggi Noodles 70g 48 11.00 528.00" in text


def test_binary_check_accepts_operators_and_rejects_pixels():
    assert BasePDFProcessor._looks_like_text_stream(b"BT (Hello) Tj ET\n")
    assert not BasePDFProcessor._looks_like_text_stream(bytes(range(256)) * 4)
    assert not BasePDFProcessor._looks_like_text_stream(b"")


# ---------------------------------------------------------------------------------------
# 2. Supplier / invoice number header parsing
# ---------------------------------------------------------------------------------------

HEADER = "S| Item Description HSN Qty Unit Rate MRP Amount"


def test_split_title_and_clipped_invoice_label():
    lines = ['"voice No: INV-00427', "SRI", "LAKSHMI", "WHOLESALE", "TRADERS", "Date: 08/10/2026",
             "14 Market Road, Vijayawada GSTIN 37ABCDE1234F1Z5", HEADER, "1 Aashirvaad Atta 5kg 1101 4 bag 245.00"]
    meta = extract_metadata(lines, HEADER)
    assert meta["supplier_name"] == "SRI LAKSHMI WHOLESALE TRADERS"
    assert meta["invoice_number"] == "INV-00427"
    assert meta["invoice_date"] == "08/10/2026"


@pytest.mark.parametrize("lines,supplier,number", [
    (["Balaji Traders", "Invoice No: BT-2024-01", "Date: 01/02/2026"], "Balaji Traders", "BT-2024-01"),
    (["TAX INVOICE", "Metro Cash & Carry Wholesale", "Inv No. MCC/88"], "Metro Cash & Carry Wholesale", "MCC/88"),
    (["Ph No: 98480 12345", "Krishna Provisions Store", "Bill No: 77"], "Krishna Provisions Store", "77"),
    (["Order # 5512", "Gupta Kirana General Store"], "Gupta Kirana General Store", None),
])
def test_existing_header_layouts_unchanged(lines, supplier, number):
    meta = extract_metadata(lines + [HEADER], HEADER)
    assert meta["supplier_name"] == supplier
    assert meta["invoice_number"] == number


def test_field_line_is_never_the_supplier_even_as_fallback():
    meta = extract_metadata(["Invoice No: 12345", "Date: 01/01/2026", HEADER], HEADER)
    assert meta["supplier_name"] is None  # nothing invented


# ---------------------------------------------------------------------------------------
# 3. Misread decimal point: suggestion only
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,qty,amount,expected", [
    ("58575", 12, 705.0, 58.75),      # point read as a digit
    (58575.0, 12, 705.0, 58.75),
    ("5875", 12, 705.0, 58.75),       # point dropped
    ("2450", 4, 980.0, 245.0),
    ("245.00", 4, 980.0, None),       # already right: nothing to suggest
    ("9999", 3, 10.0, None),          # no single-point reading explains the amount
    ("12", 3, 3.6, None),             # too short to judge
])
def test_misread_decimal_rate_candidates(raw, qty, amount, expected):
    assert suggest_misread_decimal_rate(raw, qty, amount) == expected


def test_ambiguous_readings_give_no_suggestion():
    # 1111 x 1 = 11.11 has two single-point readings that fit equally -> no guess
    assert suggest_misread_decimal_rate("1111", 1, 1.111 * 10) is None


engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine)


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_api_keeps_value_and_suggests_correction(monkeypatch):
    """Through /invoices/extract: the printed values are kept, review is required and the
    decimal reading is offered via the existing suggestions / suggested_rate fields."""
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = _get_db
    try:
        item = ExtractedInvoiceItem(
            item_id="it1", raw_product_name="MDH Jeera Powder 100g", quantity=Decimal("12"),
            purchase_price=Decimal("58575.00"), printed_amount=Decimal("705.00"), unit="pcs",
            validation_status="MISMATCH",
            validation_issues=["Arithmetic mismatch: expected ₹702900.00 (12.000 × ₹58575.00), but invoice printed ₹705.00"],
        )
        fake = ExtractedInvoice(invoice_id="inv_test", original_filename="x.png", status="NEEDS_REVIEW", items=[item],
                                metadata=InvoiceProcessingMetadata(filename="x.png"))

        class FakePipeline:
            def __init__(self, *a, **k):
                pass

            def process(self, *a, **k):
                return fake

        monkeypatch.setattr(invoice_service, "InvoicePipeline", FakePipeline)
        client = TestClient(app)
        email = f"fix{uuid.uuid4().hex[:6]}@example.com"
        client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
        token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        client.post("/api/v1/shops", json={"shop_name": "K", "owner_name": "R", "business_type": "Grocery/Kirana",
                                           "location": "B"}, headers=h)
        res = client.post("/api/v1/invoices/extract", files={"file": ("x.png", io.BytesIO(b"\x89PNG\r\n\x1a\n0000"),
                                                                        "image/png")}, headers=h)
        assert res.status_code == 200, res.text
        line = res.json()["items"][0]
        assert line["purchase_price"] == 58575.0  # never silently changed
        assert line["line_total"] == 705.0
        assert line["needs_review"] is True
        assert line["suggested_rate"] == 58.75
        assert any("misread decimal point" in s for s in line["suggestions"])
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
