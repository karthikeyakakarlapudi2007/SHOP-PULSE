"""
Invoice header data integrity: supplier, invoice number and invoice date are taken only from
the invoice or typed by the user - never invented - and duplicate detection relies only on
real invoice numbers.

Covers: extracted vs not-detected metadata (1-6), manual entry (7), confirmation (8),
duplicate detection with valid numbers (9), no false duplicates without numbers (10),
existing records remain accessible (11) and unchanged extraction output (12).
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from api.deps import get_db
from db.models.purchase import Purchase
from db.models.supplier import Supplier
from db.session import Base
from main import app
from schemas.invoice import InvoiceConfirmRequest, parse_invoice_date

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def auth():
    email = f"meta{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/shops", json={"shop_name": "Kirana Mart", "owner_name": "Ramesh",
                                       "business_type": "Grocery/Kirana", "location": "Bengaluru"}, headers=h)
    return h


ITEMS = [{"name": "Tata Salt 1kg", "quantity": 10, "unit": "pkt", "purchase_price": 22.0,
          "selling_price": 28.0, "line_amount": 220.0}]


def confirm(h, **header):
    return client.post("/api/v1/invoices/confirm", json={**header, "items": ITEMS}, headers=h)


def extract_text(h, text: str):
    res = client.post("/api/v1/invoices/extract", files={"file": ("bill.txt", io.BytesIO(text.encode()), "text/plain")},
                      headers=h)
    assert res.status_code == 200, res.text
    return res.json()


TABLE = ("Item Description    Qty    Rate    Total\n"
         "Tata Salt 1kg       24     22.00   528.00\n"
         "Basmati Rice 5kg     5     450.00  2250.00\n")


# ---------------------------------------------------------------- 1-6, 12: extraction

def test_header_details_extracted_when_printed():
    h = auth()
    data = extract_text(h, "Metro Cash & Carry Wholesale\nInvoice No: MCC/2026/8942   Date: 15/09/2026\n" + TABLE)
    assert "Metro Cash & Carry" in data["supplier_name"]          # 3
    assert data["invoice_number"] == "MCC/2026/8942"               # 1
    assert data["invoice_date"] == "15/09/2026"                    # 5
    # 12: line items extracted exactly as before
    salt = next(i for i in data["items"] if "tata salt" in i["product_name"].lower())
    assert (salt["quantity"], salt["purchase_price"], salt["line_total"]) == (24, 22.0, 528.0)


def test_missing_header_details_are_not_invented():
    h = auth()
    data = extract_text(h, TABLE)
    assert data["supplier_name"] is None                           # 4
    assert data["invoice_number"] is None                          # 2
    assert data["invoice_date"] is None                            # 6
    assert len(data["items"]) >= 2                                 # products still reviewable


# ---------------------------------------------------------------- 7-8: manual entry + confirmation

def test_manually_entered_details_are_saved_as_typed():
    h = auth()
    res = confirm(h, supplier_name="  Balaji Traders ", invoice_number=" BT-77 ", invoice_date="08/10/2026")
    assert res.status_code == 201, res.text
    db = TestingSessionLocal()
    try:
        p = db.query(Purchase).one()
        assert (p.invoice_number, p.invoice_date, p.supplier.supplier_name) == ("BT-77", "08/10/2026", "Balaji Traders")
    finally:
        db.close()


def test_confirm_without_details_stores_unknown_not_placeholders():
    h = auth()
    res = confirm(h, supplier_name="", invoice_number="  ", invoice_date="")
    assert res.status_code == 201, res.text
    db = TestingSessionLocal()
    try:
        p = db.query(Purchase).one()
        assert p.invoice_number is None and p.invoice_date is None and p.supplier_id is None
        assert db.query(Supplier).count() == 0  # no "Generic Supplier" row created
    finally:
        db.close()


@pytest.mark.parametrize("date", ["08/10/2026", "8-10-26", "08.10.2026", "2026-10-08", "2026/10/08", "12 Oct 2026"])
def test_valid_date_formats_accepted_unchanged(date):
    req = InvoiceConfirmRequest(invoice_date=date, items=ITEMS)
    assert req.invoice_date == date
    assert parse_invoice_date(date) is not None


@pytest.mark.parametrize("date", ["31/02/2026", "12/31/2026", "tomorrow", "2026-13-01", "00/10/2026"])
def test_invalid_dates_rejected_with_clear_message(date):
    h = auth()
    res = confirm(h, invoice_number="X-1", invoice_date=date)
    assert res.status_code == 422
    assert "not a valid invoice date" in res.text
    db = TestingSessionLocal()
    try:
        assert db.query(Purchase).count() == 0  # nothing saved
    finally:
        db.close()


# ---------------------------------------------------------------- 9-10: duplicate detection

def test_duplicate_blocked_for_same_valid_invoice_number():
    h = auth()
    assert confirm(h, supplier_name="Balaji Traders", invoice_number="BT-100").status_code == 201
    again = confirm(h, supplier_name="Balaji Traders", invoice_number="BT-100")
    assert again.status_code == 409 and "already added to stock" in again.json()["detail"]
    # Same number read with different letter case is still the same invoice
    assert confirm(h, supplier_name="balaji traders", invoice_number="bt-100").status_code == 409
    # Same number from a different supplier is a different invoice
    assert confirm(h, supplier_name="Krishna Stores", invoice_number="BT-100").status_code == 201


def test_missing_invoice_numbers_never_flagged_as_duplicates():
    h = auth()
    for _ in range(3):
        assert confirm(h, supplier_name="Balaji Traders").status_code == 201
    for _ in range(2):
        assert confirm(h).status_code == 201
    db = TestingSessionLocal()
    try:
        assert db.query(Purchase).count() == 5  # nothing discarded
    finally:
        db.close()


# ---------------------------------------------------------------- 11: existing records

def test_existing_records_remain_accessible():
    """Records saved earlier - including old placeholder values - are listed and readable unchanged."""
    h = auth()
    first = confirm(h, supplier_name="Generic Supplier", invoice_number="INV-4462", invoice_date="2026-11-17")
    second = confirm(h)  # no details at all
    assert first.status_code == 201 and second.status_code == 201
    listing = client.get("/api/v1/purchases", headers=h)
    assert listing.status_code == 200
    rows = listing.json()["items"] if isinstance(listing.json(), dict) else listing.json()
    assert len(rows) == 2
    by_id = {r["id"]: r for r in rows}
    old = client.get(f"/api/v1/purchases/{first.json()['purchase_id']}", headers=h).json()
    assert (old["invoice_number"], old["invoice_date"]) == ("INV-4462", "2026-11-17")
    blank = by_id[second.json()["purchase_id"]]
    assert blank["invoice_number"] is None and blank["invoice_date"] is None
