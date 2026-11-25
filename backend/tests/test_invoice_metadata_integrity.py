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


# -----------------------------------------------------------------------------
# Stage 5.2 Header Regression & Integrity Tests (Scenarios 1 - 10)
# -----------------------------------------------------------------------------

def test_stage52_scenario_01_supplier_name_extracted_side_by_side_with_invoice_no():
    """Supplier name printed on the same line as invoice number or date is extracted cleanly."""
    h = auth()
    text = (
        "SRI LAKSHMI WHOLESALE TRADERS Invoice No: INV-00427\n"
        "14 Market Road, Vijayawada GSTIN 37ABCDE1234F1Z5 Date: 08/10/2026\n"
        + TABLE
    )
    data = extract_text(h, text)
    assert data["supplier_name"] == "SRI LAKSHMI WHOLESALE TRADERS"
    assert data["invoice_number"] == "INV-00427"
    assert data["invoice_date"] == "08/10/2026"


def test_stage52_scenario_02_invoice_number_extracted_with_punctuation():
    """Alphanumeric invoice numbers with hyphens and slashes are preserved faithfully."""
    h = auth()
    text = (
        "Balaji Agro Traders\n"
        "Invoice Number: BLJ/2026-27/0894\n"
        + TABLE
    )
    data = extract_text(h, text)
    assert data["supplier_name"] == "Balaji Agro Traders"
    assert data["invoice_number"] == "BLJ/2026-27/0894"


def test_stage52_scenario_03_missing_supplier_name_stays_none():
    """When no supplier name is printed, supplier_name remains None and is never invented."""
    h = auth()
    text = (
        "Invoice No: INV-9988 Date: 01/01/2026\n"
        + TABLE
    )
    data = extract_text(h, text)
    assert data["supplier_name"] is None
    assert data["invoice_number"] == "INV-9988"
    assert data["invoice_date"] == "01/01/2026"


def test_stage52_scenario_04_missing_invoice_number_stays_none():
    """When no invoice number is printed, invoice_number remains None and is never invented."""
    h = auth()
    text = (
        "Ganesh Wholesale Mart\n"
        "Date: 14/02/2026\n"
        + TABLE
    )
    data = extract_text(h, text)
    assert data["supplier_name"] == "Ganesh Wholesale Mart"
    assert data["invoice_number"] is None
    assert data["invoice_date"] == "14/02/2026"


@pytest.mark.parametrize("header_line,expected_inv", [
    ("Invoice No: INV-101", "INV-101"),
    ("Invoice Number: 2026-0042", "2026-0042"),
    ("Bill No: B-7788", "B-7788"),
    ("Bill Number: BL-990", "BL-990"),
    ("Invoice # 4455", "4455"),
    ("Bill # B99", "B99"),
    ("Inv No. INV/88", "INV/88"),
    ("Invoice: INV-COLON-1", "INV-COLON-1"),
    ("voice no: VC-11", "VC-11"),
    ("nvoice number: NV-22", "NV-22"),
])
def test_stage52_scenario_05_different_header_label_formats(header_line, expected_inv):
    """Common label variations and OCR clippings are recognised."""
    h = auth()
    text = f"Balaji Provisions\n{header_line}\n" + TABLE
    data = extract_text(h, text)
    assert data["invoice_number"] == expected_inv


def test_stage52_scenario_06_noisy_ocr_text_and_split_delimiters():
    """Noisy OCR whitespace around delimiters (e.g. 'INV - 00427') is normalized."""
    h = auth()
    text = (
        "  *** BALAJI WHOLESALE TRADERS ***  \n"
        "Invoice No :  INV - 00427 \n"
        "Date : 08 / 10 / 2026\n"
        + TABLE
    )
    data = extract_text(h, text)
    assert data["supplier_name"] == "BALAJI WHOLESALE TRADERS"
    assert data["invoice_number"] == "INV-00427"


def test_stage52_scenario_07_supplier_vs_table_heading_confusion():
    """Table headings (Item Description, Qty, Rate, Total) are NEVER accepted as supplier name."""
    h = auth()
    # Invoice without supplier, starting directly with table headings
    text = (
        "Tax Invoice\n"
        "Particulars Qty UOM Rate MRP Amount\n"
        "Tata Salt 1kg 10 pkt 22.00 28.00 220.00\n"
    )
    data = extract_text(h, text)
    assert data["supplier_name"] is None


def test_stage52_scenario_08_invoice_number_vs_gstin_phone_date_order_confusion():
    """GSTIN, phone numbers, dates, and Order numbers are never confused with invoice number."""
    h = auth()
    text = (
        "Sri Lakshmi Enterprises\n"
        "GSTIN: 37ABCDE1234F1Z5\n"
        "Ph: 9876543210\n"
        "Date: 08/10/2026\n"
        "Order No: ORD-9988\n"
        "Purchase Order: PO-5544\n"
        + TABLE
    )
    data = extract_text(h, text)
    assert data["supplier_name"] == "Sri Lakshmi Enterprises"
    # Order No and PO No are NOT invoice numbers; since no invoice number is present, stays None
    assert data["invoice_number"] is None
    assert data["gstin"] == "37ABCDE1234F1Z5"
    assert data["invoice_date"] == "08/10/2026"


def test_stage52_scenario_09_existing_supplier_matching_on_confirm():
    """When confirming with a supplier name matching an existing supplier, links to existing supplier row."""
    h = auth()
    # Confirm first invoice with supplier
    res1 = confirm(h, supplier_name="Balaji Traders", invoice_number="INV-A1")
    assert res1.status_code == 201

    db = TestingSessionLocal()
    try:
        assert db.query(Supplier).count() == 1
        supplier_id = db.query(Supplier).first().id
    finally:
        db.close()

    # Confirm second invoice with same supplier name
    res2 = confirm(h, supplier_name="balaji traders", invoice_number="INV-A2")
    assert res2.status_code == 201

    db = TestingSessionLocal()
    try:
        assert db.query(Supplier).count() == 1  # Reused existing supplier, didn't create duplicate
        p2 = db.query(Purchase).filter(Purchase.invoice_number == "INV-A2").first()
        assert p2.supplier_id == supplier_id
    finally:
        db.close()


def test_stage52_scenario_10_image_fixtures_remain_correct():
    """Verifies that hdr_full.png extracts supplier name and invoice number accurately."""
    from doc_prep_dataset import PAGE_1_ITEMS, render_invoice_page
    import cv2
    from services.invoice import extract_invoice_from_bytes

    page = render_invoice_page(PAGE_1_ITEMS).image
    _, png_bytes = cv2.imencode(".png", page)
    file_bytes = png_bytes.tobytes()

    db = TestingSessionLocal()
    try:
        shop = db.query(Purchase).first()
        # Just create a test shop UUID
        shop_uuid = uuid.uuid4()
        res = extract_invoice_from_bytes(file_bytes, "hdr_full.png", db, shop_uuid)
        assert res.supplier_name == "SRI LAKSHMI WHOLESALE TRADERS"
        assert res.invoice_number == "INV-00427"
        assert res.invoice_date == "08/10/2026"
        assert res.gstin == "37ABCDE1234F1Z5"
        assert len(res.items) >= 5
    finally:
        db.close()


def test_stage612_blank_invoice_number_normalization_lifecycle():
    """Stage 6.1.2: Exhaustive validation of blank invoice number normalization and lifecycle:
    1. NULL invoice_number remains NULL.
    2. Empty string is normalized to NULL.
    3. Whitespace-only string is normalized to NULL.
    4. Multiple unnumbered purchases are permitted without duplicate collisions.
    5. Numbered invoice duplicates remain strictly blocked.
    6. Case and whitespace normalization on numbered invoices is strictly enforced.
    """
    h = auth()

    # 1. NULL invoice_number remains NULL
    res_null = confirm(h, supplier_name="Test Supplier", invoice_number=None)
    assert res_null.status_code == 201
    pid_null = res_null.json()["purchase_id"]

    # 2. Empty string is normalized to NULL
    res_empty = confirm(h, supplier_name="Test Supplier", invoice_number="")
    assert res_empty.status_code == 201
    pid_empty = res_empty.json()["purchase_id"]

    # 3. Whitespace-only invoice number is normalized to NULL
    res_ws = confirm(h, supplier_name="Test Supplier", invoice_number="   ")
    assert res_ws.status_code == 201
    pid_ws = res_ws.json()["purchase_id"]

    # 4. Verify all three records have NULL in DB (multiple unnumbered allowed)
    db = TestingSessionLocal()
    try:
        p_null = db.query(Purchase).filter(Purchase.id == uuid.UUID(pid_null)).first()
        p_empty = db.query(Purchase).filter(Purchase.id == uuid.UUID(pid_empty)).first()
        p_ws = db.query(Purchase).filter(Purchase.id == uuid.UUID(pid_ws)).first()
        assert p_null.invoice_number is None
        assert p_empty.invoice_number is None
        assert p_ws.invoice_number is None
    finally:
        db.close()

    # 5. Numbered invoice confirmation succeeds
    res_num = confirm(h, supplier_name="Test Supplier", invoice_number="INV-612-TEST")
    assert res_num.status_code == 201

    # Exact duplicate blocked
    res_num_dup = confirm(h, supplier_name="Test Supplier", invoice_number="INV-612-TEST")
    assert res_num_dup.status_code == 409
    assert "already added to stock" in res_num_dup.json()["detail"]

    # 6. Case and whitespace normalization blocked
    res_case = confirm(h, supplier_name="Test Supplier", invoice_number="  inv-612-test  ")
    assert res_case.status_code == 409
    assert "already added to stock" in res_case.json()["detail"]


