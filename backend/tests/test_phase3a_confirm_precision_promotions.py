"""
Phase 3A follow-up: three-decimal precision at confirmation / storage / API, and paid + free units.

Policy verified here:
* printed 3-decimal values are stored and returned as printed (no rounding to paise);
* a calculated line amount keeps 3 decimals;
* "10+1": 11 units received into stock, the printed rate and amount kept, no cost redistributed;
* a printed free line (rate 0.00) is recorded as printed but never becomes the product's cost;
* free units are posted only with explicit confirmation (confirm_free_units).
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from api.deps import get_db
from db.models.product import Product
from db.models.purchase import Purchase
from db.models.purchase_item import PurchaseItem
from db.session import Base
from main import app

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)


def _db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = _db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def auth():
    email = f"p3a{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/shops", json={"shop_name": "Kirana", "owner_name": "R", "business_type": "Grocery/Kirana",
                                       "location": "B"}, headers=h)
    return h


def confirm(h, items, **extra):
    return client.post("/api/v1/invoices/confirm", json={"invoice_number": f"T-{uuid.uuid4().hex[:6]}",
                                                        "items": items, **extra}, headers=h)


def rows():
    db = Session()
    try:
        return (db.query(Purchase).all(), db.query(PurchaseItem).all(), {p.name: p for p in db.query(Product).all()})
    finally:
        db.close()


# ------------------------------------------------------------------------------------- precision


def test_three_decimal_values_stored_and_returned_as_printed():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "BUTTER COOKIES 5RS", "quantity": 12, "purchase_price": 5.249, "selling_price": 5.0,
                     "line_amount": 62.988}])
    assert r.status_code == 201, r.text
    assert r.json()["total_amount"] == 62.988
    purchases, items, products = rows()
    assert purchases[0].total_amount == 62.988 and items[0].line_amount == 62.988
    assert items[0].purchase_price == 5.249 and products["BUTTER COOKIES 5RS"].purchase_price == 5.249


def test_calculated_line_amount_keeps_three_decimals():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "FRUIT NUT 10RS", "quantity": 12, "purchase_price": 7.143, "selling_price": 10.0}])
    assert r.status_code == 201, r.text
    _, items, _ = rows()
    assert items[0].line_amount == 85.716  # was round(..., 2) -> 85.72
    assert r.json()["total_amount"] == 85.716


def test_two_decimal_values_unchanged():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "SALT", "quantity": 20, "purchase_price": 22.0, "selling_price": 28.0, "line_amount": 440.0},
                    {"unit": "pcs", "name": "SUGAR", "quantity": 3, "purchase_price": 42.0, "selling_price": 48.0}])
    assert r.status_code == 201 and r.json()["total_amount"] == 566.0


def test_purchase_api_returns_three_decimals():
    h = auth()
    confirm(h, [{"unit": "pcs", "name": "BISCUIT", "quantity": 12, "purchase_price": 5.249, "selling_price": 5.0, "line_amount": 62.988}])
    lst = client.get("/api/v1/purchases", headers=h).json()["items"]
    assert lst[0]["total_amount"] == 62.988


# ------------------------------------------------------------------------------------- promotions


def test_paid_plus_free_requires_explicit_confirmation():
    h = auth()
    item = {"unit": "pcs", "name": "SOAP 75G", "quantity": 11, "paid_quantity": 10, "free_quantity": 1, "purchase_price": 35.0,
            "selling_price": 40.0, "line_amount": 350.0}
    r = confirm(h, [item])
    assert r.status_code == 422 and "must be confirmed" in r.text
    purchases, _, products = rows()
    assert purchases == [] and products == {}  # nothing posted


def test_paid_plus_free_posts_received_units_and_keeps_printed_values():
    h = auth()
    item = {"unit": "pcs", "name": "SOAP 75G", "quantity": 11, "paid_quantity": 10, "free_quantity": 1, "purchase_price": 35.0,
            "selling_price": 40.0, "line_amount": 350.0}
    r = confirm(h, [item], confirm_free_units=True)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["promotional_lines"][0] == {"name": "SOAP 75G", "received_quantity": 11, "paid_quantity": 10.0,
                                            "free_quantity": 1.0, "is_free_item": False, "purchase_price": 35.0,
                                            "line_amount": 350.0}
    _, items, products = rows()
    assert products["SOAP 75G"].current_stock == 11
    assert products["SOAP 75G"].purchase_price == 35.0  # printed rate: no redistribution (not 350/11)
    assert items[0].quantity == 11 and items[0].purchase_price == 35.0 and items[0].line_amount == 350.0


def test_paid_plus_free_without_printed_amount_uses_paid_units():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "SOAP 75G", "quantity": 11, "paid_quantity": 10, "free_quantity": 1,
                     "purchase_price": 35.0, "selling_price": 40.0}], confirm_free_units=True)
    _, items, _ = rows()
    assert r.status_code == 201 and items[0].line_amount == 350.0  # 10 paid x 35, not 11 x 35


def test_inconsistent_paid_free_breakdown_rejected():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "SOAP", "quantity": 12, "paid_quantity": 10, "free_quantity": 1, "purchase_price": 35.0,
                     "selling_price": 40.0}], confirm_free_units=True)
    assert r.status_code == 422 and "paid + free" in r.text


def test_free_line_never_sets_zero_cost_on_existing_product():
    h = auth()
    confirm(h, [{"unit": "pcs", "name": "REFILL POUCH 180ML", "quantity": 10, "purchase_price": 8.0, "selling_price": 10.0}])
    r = confirm(h, [{"unit": "pcs", "name": "REFILL POUCH 180ML", "quantity": 4, "purchase_price": 0.0, "selling_price": 10.0,
                     "line_amount": 0.0, "is_free_item": True}], confirm_free_units=True)
    assert r.status_code == 201, r.text
    _, items, products = rows()
    assert products["REFILL POUCH 180ML"].current_stock == 14
    assert products["REFILL POUCH 180ML"].purchase_price == 8.0  # cost not overwritten with 0.00
    free_row = [i for i in items if i.purchase_price == 0.0][0]
    assert free_row.quantity == 4 and free_row.line_amount == 0.0  # printed values recorded


def test_free_line_for_new_product_leaves_cost_unknown_not_zero():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "REFILL 180ML", "quantity": 6, "purchase_price": 0.0, "selling_price": 89.0,
                     "line_amount": 0.0, "is_free_item": True}], confirm_free_units=True)
    assert r.status_code == 201, r.text
    _, _, products = rows()
    assert products["REFILL 180ML"].current_stock == 6 and products["REFILL 180ML"].purchase_price is None
    got = client.get("/api/v1/products", headers=h).json()["items"][0]
    assert got["purchase_price"] is None


def test_ordinary_invoice_needs_no_free_unit_confirmation():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "SALT", "quantity": 20, "purchase_price": 22.0, "selling_price": 28.0}])
    assert r.status_code == 201 and r.json()["promotional_lines"] == []


# ------------------------------------------------------------------------------------- P0: whole-unit stock


@pytest.mark.parametrize("qty,unit", [(2.5, "pcs"), (0.75, "packet"), (0.4, "box"), (1.5, "dozen")])
def test_p0_fractional_quantity_in_a_whole_number_unit_blocks_the_invoice_and_posts_nothing(qty, unit):
    """2.5 pcs is never rounded to 3 (or 0.4 box to 1): the invoice is rejected with a clear message and no
    stock, product or purchase is written - not even for its whole-number lines. (Phase 4: kg, g, L and ml
    may be fractional, see the next test.)"""
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "SALT 1KG", "quantity": 20, "purchase_price": 22.0, "selling_price": 25.0},
                    {"name": "SUGAR PACK", "quantity": qty, "unit": unit, "purchase_price": 44.0,
                     "selling_price": 50.0}])
    assert r.status_code == 422
    assert "fractional stock quantities are not currently supported" in r.text
    purchases, items, products = rows()
    assert purchases == [] and items == [] and products == {}


@pytest.mark.parametrize("qty,unit", [(2.5, "kg"), (0.75, "L"), (250.5, "g"), (0.125, "kg")])
def test_fractional_quantity_in_a_measure_unit_is_received_exactly(qty, unit):
    """Phase 4 (approved D-1): kg, g, L and ml hold fractional stock; nothing is rounded."""
    h = auth()
    r = confirm(h, [{"name": "SUGAR LOOSE", "quantity": qty, "unit": unit, "purchase_price": 44.0, "selling_price": 50.0}])
    assert r.status_code == 201, r.text
    _, items, products = rows()
    assert products["SUGAR LOOSE"].current_stock == qty and items[0].quantity == qty


def test_p0_fractional_paid_or_free_units_are_rejected_too():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "OIL 1L", "quantity": 11, "paid_quantity": 10.5, "free_quantity": 0.5,
                     "purchase_price": 120.0, "selling_price": 140.0}], confirm_free_units=True)
    assert r.status_code == 422 and "not currently supported" in r.text
    assert rows()[2] == {}


def test_p0_whole_number_quantities_behave_as_before():
    h = auth()
    r = confirm(h, [{"unit": "pcs", "name": "SALT 1KG", "quantity": 20, "purchase_price": 22.0, "selling_price": 25.0},
                    {"name": "RICE 5KG", "quantity": 3.0, "unit": "bag", "purchase_price": 300.0, "selling_price": 340.0}])
    assert r.status_code == 201, r.text
    _, items, products = rows()
    assert products["SALT 1KG"].current_stock == 20 and products["RICE 5KG"].current_stock == 3
    assert sorted(i.quantity for i in items) == [3, 20]
    # existing stock is incremented in whole units, as before
    assert confirm(h, [{"unit": "pcs", "name": "SALT 1KG", "quantity": 5, "purchase_price": 22.0, "selling_price": 25.0}]).status_code == 201
    assert rows()[2]["SALT 1KG"].current_stock == 25
