"""
Dedicated Integration Test Suite for Stage 4B.2:
Voice-to-Bill Universal Pricing Engine Integration

Covers all 15 scenarios specified in Stage 4B.2 Plan:
1. Mass Conversion (g to kg)
2. Volume Conversion (ml to L)
3. Sub-Unit Basis (per 100g)
4. Discrete / Packet Basis (per packet)
5. Multi-Unit Basis (per 12 pcs)
6. Fractional Quantities (2.5 kg)
7. WHOLESALE_ONLY Whole Container
8. WHOLESALE_ONLY Fractional Rejection
9. WHOLESALE_ONLY Loose Unit Rejection
10. NEEDS_REVIEW Gate Rejection
11. INCOMPLETE Gate Rejection
12. Spoken Price Matches Catalog
13. Spoken Price Exceeds Statutory MRP
14. Incompatible Spoken Units Rejection
15. End-to-End Voice-to-POS Checkout
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from db.session import Base
from api.deps import get_db
from schemas.voice import VoiceProductCandidate
from services.inventory_matcher import make_matched_item, match_items_to_inventory, VoiceItemError
from services.voice_parser import ExtractedItem

# Isolated in-memory SQLite database for test execution
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


@pytest.fixture
def api():
    c = TestClient(app)
    email = f"voice_stage4b2_{uuid.uuid4().hex[:8]}@example.com"
    c.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    login_res = c.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    shop_res = c.post("/api/v1/shops", json={
        "shop_name": "Stage 4B2 Voice Store",
        "owner_name": "Test Owner",
        "business_type": "Grocery/Kirana",
        "location": "Hyderabad"
    }, headers=headers)
    assert shop_res.status_code == 201, shop_res.text
    return c, headers


def _cand(
    name: str,
    unit: str,
    price: float = 50.0,
    stock: float = 100.0,
    basis_qty: float = 1.0,
    basis_unit: str = None,
    status: str = "VERIFIED",
    mrp: float = None,
    pid: str = None
) -> VoiceProductCandidate:
    return VoiceProductCandidate(
        id=pid or str(uuid.uuid4()),
        name=name,
        selling_price=price,
        current_stock=stock,
        unit=unit,
        price_basis_quantity=basis_qty,
        price_basis_unit=basis_unit or unit,
        pricing_status=status,
        mrp=mrp,
    )


# ----------------------------------------------------------------------------
# 1. Mass Conversion (g to kg)
# ----------------------------------------------------------------------------
def test_01_mass_conversion_grams_to_kg():
    prod = _cand("Basmati Rice", unit="kg", price=80.0, stock=50.0)
    item = ExtractedItem(name="basmati rice", quantity=500, unit="g")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 0.5
    assert matched.unit == "kg"
    assert matched.total_price == 40.0
    assert matched.spoken_quantity == "500 g"
    assert matched.price_source == "catalogue"


# ----------------------------------------------------------------------------
# 2. Volume Conversion (ml to L)
# ----------------------------------------------------------------------------
def test_02_volume_conversion_ml_to_liter():
    prod = _cand("Sunflower Oil", unit="L", price=120.0, stock=50.0)
    item = ExtractedItem(name="sunflower oil", quantity=750, unit="ml")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 0.75
    assert matched.unit == "L"
    assert matched.total_price == 90.0
    assert matched.spoken_quantity == "750 ml"
    assert matched.price_source == "catalogue"


# ----------------------------------------------------------------------------
# 3. Sub-Unit Basis (per 100g)
# ----------------------------------------------------------------------------
def test_03_sub_unit_basis_per_100g():
    prod = _cand("Chilli Powder", unit="g", price=30.0, stock=1000.0, basis_qty=100.0, basis_unit="g")
    item = ExtractedItem(name="chilli powder", quantity=250, unit="g")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 250
    assert matched.unit == "g"
    assert matched.total_price == 75.0
    assert matched.unit_price == 0.3
    assert matched.price_source == "catalogue"


# ----------------------------------------------------------------------------
# 4. Discrete / Packet Basis (per packet)
# ----------------------------------------------------------------------------
def test_04_discrete_packet_basis():
    prod = _cand("Bourbon Biscuits", unit="pkt", price=20.0, stock=50.0)
    item = ExtractedItem(name="bourbon biscuits", quantity=2, unit="pkt")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 2
    assert matched.unit == "pkt"
    assert matched.total_price == 40.0
    assert matched.unit_price == 20.0


# ----------------------------------------------------------------------------
# 5. Multi-Unit Basis (per 12 pcs)
# ----------------------------------------------------------------------------
def test_05_multi_unit_basis_per_12_pcs():
    prod = _cand("Farm Fresh Eggs", unit="pcs", price=480.0, stock=100.0, basis_qty=12.0, basis_unit="pcs")
    item = ExtractedItem(name="farm fresh eggs", quantity=1, unit="pcs")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 1
    assert matched.unit == "pcs"
    assert matched.total_price == 40.0
    assert matched.unit_price == 40.0


# ----------------------------------------------------------------------------
# 6. Fractional Quantities (2.5 kg)
# ----------------------------------------------------------------------------
def test_06_fractional_quantities():
    prod = _cand("Shimla Apples", unit="kg", price=120.0, stock=30.0)
    item = ExtractedItem(name="shimla apples", quantity=2.5, unit="kg")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 2.5
    assert matched.unit == "kg"
    assert matched.total_price == 300.0


# ----------------------------------------------------------------------------
# 7. WHOLESALE_ONLY Whole Container
# ----------------------------------------------------------------------------
def test_07_wholesale_only_whole_container_allowed():
    prod = _cand("Cooking Oil Tin 15L", unit="can", price=1800.0, stock=10.0, status="WHOLESALE_ONLY")
    item = ExtractedItem(name="cooking oil tin 15l", quantity=2, unit="can")
    matched = make_matched_item(prod, item)
    assert matched.quantity == 2
    assert matched.unit == "can"
    assert matched.total_price == 3600.0


# ----------------------------------------------------------------------------
# 8. WHOLESALE_ONLY Fractional Rejection
# ----------------------------------------------------------------------------
def test_08_wholesale_only_fractional_rejected():
    prod = _cand("Cooking Oil Tin 15L", unit="can", price=1800.0, stock=10.0, status="WHOLESALE_ONLY")
    item = ExtractedItem(name="cooking oil tin 15l", quantity=1.5, unit="can")
    with pytest.raises(VoiceItemError, match="wholesale-only"):
        make_matched_item(prod, item)

    matched, _, unmatched, *_ = match_items_to_inventory([item], [prod])
    assert len(matched) == 0
    assert len(unmatched) == 1
    assert "wholesale-only" in unmatched[0].reason


# ----------------------------------------------------------------------------
# 9. WHOLESALE_ONLY Loose Unit Rejection
# ----------------------------------------------------------------------------
def test_09_wholesale_only_loose_unit_rejected():
    prod = _cand("Cooking Oil Tin 15L", unit="can", price=1800.0, stock=10.0, status="WHOLESALE_ONLY")
    item = ExtractedItem(name="cooking oil tin 15l", quantity=500, unit="ml")
    with pytest.raises(VoiceItemError, match="wholesale-only"):
        make_matched_item(prod, item)

    matched, _, unmatched, *_ = match_items_to_inventory([item], [prod])
    assert len(matched) == 0
    assert len(unmatched) == 1
    assert "wholesale-only" in unmatched[0].reason


# ----------------------------------------------------------------------------
# 10. NEEDS_REVIEW Gate Rejection
# ----------------------------------------------------------------------------
def test_10_needs_review_product_rejected():
    prod = _cand("Unverified Item", unit="kg", price=100.0, stock=10.0, status="NEEDS_REVIEW")
    item = ExtractedItem(name="unverified item", quantity=1, unit="kg")
    with pytest.raises(VoiceItemError, match="requires manager pricing review"):
        make_matched_item(prod, item)

    matched, _, unmatched, *_ = match_items_to_inventory([item], [prod])
    assert len(matched) == 0
    assert len(unmatched) == 1
    assert "manager pricing review" in unmatched[0].reason


# ----------------------------------------------------------------------------
# 11. INCOMPLETE Gate Rejection
# ----------------------------------------------------------------------------
def test_11_incomplete_product_rejected():
    prod = _cand("Incomplete Item", unit="kg", price=0.0, stock=10.0, status="INCOMPLETE")
    item = ExtractedItem(name="incomplete item", quantity=1, unit="kg")
    with pytest.raises(VoiceItemError, match="incomplete pricing"):
        make_matched_item(prod, item)

    matched, _, unmatched, *_ = match_items_to_inventory([item], [prod])
    assert len(matched) == 0
    assert len(unmatched) == 1
    assert "incomplete pricing" in unmatched[0].reason


# ----------------------------------------------------------------------------
# 12. Spoken Price Matches Catalog Rate
# ----------------------------------------------------------------------------
def test_12_spoken_price_matches_catalog():
    prod = _cand("Premium Rice", unit="kg", price=80.0, stock=50.0)
    item = ExtractedItem(name="premium rice", quantity=2, unit="kg", spoken_price=160.0)
    matched = make_matched_item(prod, item)
    assert matched.quantity == 2
    assert matched.total_price == 160.0
    assert matched.price_source == "spoken"
    assert matched.catalog_line_total == 160.0


# ----------------------------------------------------------------------------
# 13. Spoken Price Exceeds Statutory MRP
# ----------------------------------------------------------------------------
def test_13_spoken_price_exceeds_mrp_rejected():
    prod = _cand("Lifebuoy Soap", unit="pcs", price=45.0, stock=20.0, mrp=50.0)
    item = ExtractedItem(name="lifebuoy soap", quantity=1, unit="pcs", spoken_price=60.0)
    with pytest.raises(VoiceItemError, match="exceeds statutory MRP"):
        make_matched_item(prod, item)

    matched, _, unmatched, *_ = match_items_to_inventory([item], [prod])
    assert len(matched) == 0
    assert len(unmatched) == 1
    assert "exceeds statutory MRP" in unmatched[0].reason


# ----------------------------------------------------------------------------
# 14. Incompatible Spoken Units Rejection
# ----------------------------------------------------------------------------
def test_14_incompatible_spoken_units_rejected():
    prod = _cand("Tata Salt", unit="kg", price=25.0, stock=30.0)
    item = ExtractedItem(name="tata salt", quantity=500, unit="ml")
    with pytest.raises(VoiceItemError):
        make_matched_item(prod, item)

    matched, _, unmatched, *_ = match_items_to_inventory([item], [prod])
    assert len(matched) == 0
    assert len(unmatched) == 1
    assert "cannot be converted" in unmatched[0].reason or "incompatible" in unmatched[0].reason.lower()


# ----------------------------------------------------------------------------
# 15. End-to-End Voice-to-POS Checkout
# ----------------------------------------------------------------------------
def test_15_end_to_end_voice_to_pos_checkout(api):
    c, headers = api

    # 1. Create Verified Products
    res_rice = c.post("/api/v1/products", json={
        "name": "Kurnool Sona Masoori",
        "category": "Grains",
        "selling_price": 60.0,
        "purchase_price": 50.0,
        "current_stock": 100.0,
        "unit": "kg",
        "pricing_status": "VERIFIED"
    }, headers=headers)
    assert res_rice.status_code == 201, res_rice.text
    r_rice = res_rice.json()

    res_oil = c.post("/api/v1/products", json={
        "name": "Freedom Sunflower Oil",
        "category": "Edible Oil",
        "selling_price": 140.0,
        "purchase_price": 120.0,
        "current_stock": 50.0,
        "unit": "L",
        "pricing_status": "VERIFIED"
    }, headers=headers)
    assert res_oil.status_code == 201, res_oil.text
    r_oil = res_oil.json()

    # 2. Process Voice Simulation (500g Rice and 1.5L Oil)
    # 500g of 60/kg = 30.0; 1.5L of 140/L = 210.0; Subtotal = 240.0
    voice_resp = c.post("/api/v1/voice/process", json={
        "simulation_text": "500 g Kurnool Sona Masoori and 1.5 L Freedom Sunflower Oil",
        "language_code": "en-IN"
    }, headers=headers)
    assert voice_resp.status_code == 200
    vdata = voice_resp.json()
    assert vdata["unmatched_items"] == [] and vdata["ambiguous_items"] == [], f"Unmatched: {vdata['unmatched_items']}, Ambiguous: {vdata['ambiguous_items']}"
    assert len(vdata["matched_items"]) == 2
    items_by_name = {m["name"]: m for m in vdata["matched_items"]}
    assert items_by_name["Kurnool Sona Masoori"]["total_price"] == 30.0
    assert items_by_name["Kurnool Sona Masoori"]["quantity"] == 0.5
    assert items_by_name["Freedom Sunflower Oil"]["total_price"] == 210.0
    assert items_by_name["Freedom Sunflower Oil"]["quantity"] == 1.5
    assert vdata["total"] == 240.0

    # 3. Submit Checkout to POST /api/v1/sales
    sales_payload = {
        "items": [
            {
                "product_id": m["product_id"],
                "quantity": m["quantity"],
                "unit": m["unit"],
                "unit_price": m["unit_price"]
            }
            for m in vdata["matched_items"]
        ],
        "payment_method": "cash"
    }
    sale_resp = c.post("/api/v1/sales", json=sales_payload, headers=headers)
    assert sale_resp.status_code == 201
    sdata = sale_resp.json()
    assert sdata["total_amount"] == 240.0

    # 4. Verify Physical Inventory Deductions
    rice_stock = c.get(f"/api/v1/products/{r_rice['id']}", headers=headers).json()["current_stock"]
    oil_stock = c.get(f"/api/v1/products/{r_oil['id']}", headers=headers).json()["current_stock"]
    assert rice_stock == 99.5  # 100 - 0.5 kg
    assert oil_stock == 48.5   # 50 - 1.5 L
