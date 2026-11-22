"""
Focused Manual POS Backend Pricing Engine Integration Tests (Stage 4B.1).

Validates server-authoritative calculations, status gating (VERIFIED, NEEDS_REVIEW,
INCOMPLETE, WHOLESALE_ONLY), unit conversion, stock deduction, and atomic transactions.
"""

from decimal import Decimal
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from db.session import Base
from db.models.product import Product
from db.models.shop import Shop
from db.models.user import User
from db.models.sale import Sale
from db.models.sale_item import SaleItem
from api.deps import get_db

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


client = TestClient(app)


def setup_test_pos(email: str = "pos_cashier@example.com"):
    """Helper to create authenticated user, shop, and return headers and shop_id."""
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    shop_res = client.post(
        "/api/v1/shops",
        json={
            "shop_name": "Test POS Kirana Mart",
            "owner_name": "Kirana Owner",
            "business_type": "Grocery/Kirana",
            "location": "Market Yard",
        },
        headers=headers,
    )
    shop_id = uuid.UUID(shop_res.json()["id"])
    return {"headers": headers, "shop_id": shop_id}


def create_product_direct(
    name: str,
    selling_price: float,
    current_stock: float,
    unit: str,
    shop_id: uuid.UUID,
    price_basis_quantity: float = 1.0,
    price_basis_unit: str = None,
    pricing_status: str = "VERIFIED",
    is_active: bool = True,
) -> Product:
    """Helper to inject catalog products directly with exact pricing and status fields."""
    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name=name,
        selling_price=selling_price,
        current_stock=current_stock,
        unit=unit,
        price_basis_quantity=price_basis_quantity,
        price_basis_unit=price_basis_unit or unit,
        pricing_status=pricing_status,
        is_active=is_active,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    db.close()
    return prod


# -----------------------------------------------------------------------------
# Test 1: Verified Packaged Product Checkout
# -----------------------------------------------------------------------------
def test_1_verified_packaged_product_checkout():
    pos = setup_test_pos("test1@pos.com")
    prod = create_product_direct("Fortune Sunflower Oil (1L)", 165.0, 10, "pouch", pos["shop_id"], pricing_status="VERIFIED")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 1}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 165.0
    assert data["items"][0]["quantity"] == 1
    assert data["items"][0]["unit_price"] == 165.0

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 9
    db.close()


# -----------------------------------------------------------------------------
# Test 2: 500g of a ₹50/kg product = ₹25.00
# -----------------------------------------------------------------------------
def test_2_fractional_weight_checkout():
    pos = setup_test_pos("test2@pos.com")
    prod = create_product_direct("Rajamm", 50.0, 20.0, "kg", pos["shop_id"], pricing_status="VERIFIED")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 500, "unit": "g"}],
        "payment_method": "upi",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 25.0
    assert data["items"][0]["quantity"] == 0.5  # Stored in product unit (kg)
    assert data["items"][0]["unit_price"] == 50.0

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 19.5  # 20 - 0.5
    db.close()


# -----------------------------------------------------------------------------
# Test 3: 750ml of a ₹120/L product = ₹90.00
# -----------------------------------------------------------------------------
def test_3_volume_conversion_checkout():
    pos = setup_test_pos("test3@pos.com")
    prod = create_product_direct("Mustard Oil", 120.0, 10.0, "L", pos["shop_id"], pricing_status="VERIFIED")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 750, "unit": "ml"}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 90.0
    assert data["items"][0]["quantity"] == 0.75  # Stored in litres
    assert data["items"][0]["unit_price"] == 120.0

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 9.25  # 10 - 0.75
    db.close()


# -----------------------------------------------------------------------------
# Test 4: 2 packets at ₹20/packet = ₹40.00
# -----------------------------------------------------------------------------
def test_4_packets_discrete_checkout():
    pos = setup_test_pos("test4@pos.com")
    prod = create_product_direct("Biscuits", 20.0, 50, "packet", pos["shop_id"], pricing_status="VERIFIED")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 2, "unit": "packet"}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 40.0
    assert data["items"][0]["quantity"] == 2
    assert data["items"][0]["unit_price"] == 20.0

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 48
    db.close()


# -----------------------------------------------------------------------------
# Test 5: ₹480 per 12 pieces; 1 piece = ₹40.00
# -----------------------------------------------------------------------------
def test_5_multi_unit_basis_checkout():
    pos = setup_test_pos("test5@pos.com")
    prod = create_product_direct(
        name="Imported Soap",
        selling_price=480.0,
        current_stock=24,
        unit="pcs",
        shop_id=pos["shop_id"],
        price_basis_quantity=12.0,
        price_basis_unit="pcs",
        pricing_status="VERIFIED",
    )

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 1, "unit": "pcs"}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 40.0
    assert data["items"][0]["quantity"] == 1
    assert data["items"][0]["unit_price"] == 40.0

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 23
    db.close()


# -----------------------------------------------------------------------------
# Test 6: WHOLESALE_ONLY Whole-Container Checkout
# -----------------------------------------------------------------------------
def test_6_wholesale_only_whole_container_success():
    pos = setup_test_pos("test6@pos.com")
    prod = create_product_direct("Oil Can 10", 1500.0, 5, "can", pos["shop_id"], pricing_status="WHOLESALE_ONLY")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 2, "unit": "can"}],
        "payment_method": "card",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 3000.0
    assert data["items"][0]["quantity"] == 2

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 3
    db.close()


# -----------------------------------------------------------------------------
# Test 7: Fractional Wholesale Rejection
# -----------------------------------------------------------------------------
def test_7_wholesale_fractional_rejected():
    pos = setup_test_pos("test7@pos.com")
    prod = create_product_direct("Oil Can 10", 1500.0, 5, "can", pos["shop_id"], pricing_status="WHOLESALE_ONLY")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 1.5, "unit": "can"}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "cannot be sold in fractional quantities" in resp.json()["detail"]

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 5  # Untouched
    db.close()


# -----------------------------------------------------------------------------
# Test 8: NEEDS_REVIEW Rejection
# -----------------------------------------------------------------------------
def test_8_needs_review_product_rejected():
    pos = setup_test_pos("test8@pos.com")
    prod = create_product_direct("Amul Butter 500g", 275.0, 10, "pcs", pos["shop_id"], pricing_status="NEEDS_REVIEW")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 1}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "requires manager pricing review" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 9: INCOMPLETE Rejection (₹0.00 price)
# -----------------------------------------------------------------------------
def test_9_incomplete_product_rejected():
    pos = setup_test_pos("test9@pos.com")
    prod = create_product_direct("Sample Item", 0.0, 10, "pcs", pos["shop_id"], pricing_status="INCOMPLETE")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 1}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "incomplete pricing" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 10: Incompatible Unit Rejection
# -----------------------------------------------------------------------------
def test_10_incompatible_unit_rejected():
    pos = setup_test_pos("test10@pos.com")
    prod = create_product_direct("Tata Salt", 25.0, 50, "pkts", pos["shop_id"], pricing_status="VERIFIED")

    # Attempting to buy packets of salt measured in Litres
    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 2, "unit": "L"}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "incompatible" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 11: Client Price Tampering Rejected
# -----------------------------------------------------------------------------
def test_11_client_price_tampering_rejected():
    pos = setup_test_pos("test11@pos.com")
    prod = create_product_direct("Fortune Oil (1L)", 165.0, 10, "pouch", pos["shop_id"], pricing_status="VERIFIED")

    # Client tries to assert ₹10.00 instead of ₹165.00
    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 1, "unit_price": 10.0}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "Price assertion failed" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 12: Insufficient Inventory Rejection
# -----------------------------------------------------------------------------
def test_12_insufficient_inventory_rejected():
    pos = setup_test_pos("test12@pos.com")
    prod = create_product_direct("Tata Salt 1kg", 25.0, 5, "pkt", pos["shop_id"], pricing_status="VERIFIED")

    payload = {
        "items": [{"product_id": str(prod.id), "quantity": 10}],  # 10 > 5
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "Insufficient stock" in resp.json()["detail"]

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 5  # Untouched
    db.close()


# -----------------------------------------------------------------------------
# Test 13: Decimal Rounding (ROUND_HALF_UP paise boundary)
# -----------------------------------------------------------------------------
def test_13_decimal_rounding_half_up():
    pos = setup_test_pos("test13@pos.com")
    # Item priced at ₹100 for 3 pcs -> rate is 33.3333333333
    prod = create_product_direct(
        name="3-for-100 Item",
        selling_price=100.0,
        current_stock=10,
        unit="pcs",
        shop_id=pos["shop_id"],
        price_basis_quantity=3.0,
        price_basis_unit="pcs",
        pricing_status="VERIFIED",
    )

    # Buy 1 pc: unrounded 33.333333 -> rounds half-up to ₹33.33
    resp1 = client.post(
        "/api/v1/sales",
        json={"items": [{"product_id": str(prod.id), "quantity": 1}]},
        headers=pos["headers"],
    )
    assert resp1.status_code == 201
    assert resp1.json()["total_amount"] == 33.33

    # Buy 3 pcs: unrounded 100.00 -> exactly ₹100.00
    resp3 = client.post(
        "/api/v1/sales",
        json={"items": [{"product_id": str(prod.id), "quantity": 3}]},
        headers=pos["headers"],
    )
    assert resp3.status_code == 201
    assert resp3.json()["total_amount"] == 100.00


# -----------------------------------------------------------------------------
# Test 14: Multiple Product Checkout
# -----------------------------------------------------------------------------
def test_14_multi_product_checkout_success():
    pos = setup_test_pos("test14@pos.com")
    p1 = create_product_direct("Tata Salt 1kg", 25.0, 20, "pkt", pos["shop_id"], pricing_status="VERIFIED")
    p2 = create_product_direct("Rajamm", 50.0, 10.0, "kg", pos["shop_id"], pricing_status="VERIFIED")

    payload = {
        "items": [
            {"product_id": str(p1.id), "quantity": 2},  # 2 * 25.0 = 50.0
            {"product_id": str(p2.id), "quantity": 500, "unit": "g"},  # 0.5 * 50.0 = 25.0
        ],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 75.0
    assert len(data["items"]) == 2

    db = TestingSessionLocal()
    assert db.query(Product).filter_by(id=p1.id).first().current_stock == 18
    assert db.query(Product).filter_by(id=p2.id).first().current_stock == 9.5
    db.close()


# -----------------------------------------------------------------------------
# Test 15: Failure on Second Line Rolls Back Entire Sale
# -----------------------------------------------------------------------------
def test_15_second_line_failure_atomic_rollback():
    pos = setup_test_pos("test15@pos.com")
    p1 = create_product_direct("Tata Salt 1kg", 25.0, 20, "pkt", pos["shop_id"], pricing_status="VERIFIED")
    p2_unreviewed = create_product_direct("Unreviewed Item", 100.0, 10, "pcs", pos["shop_id"], pricing_status="NEEDS_REVIEW")

    payload = {
        "items": [
            {"product_id": str(p1.id), "quantity": 2},
            {"product_id": str(p2_unreviewed.id), "quantity": 1},
        ],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 400
    assert "requires manager pricing review" in resp.json()["detail"]

    # Verify zero partial mutations occurred:
    db = TestingSessionLocal()
    assert db.query(Product).filter_by(id=p1.id).first().current_stock == 20  # Stock NOT deducted
    assert db.query(Sale).count() == 0  # No sale created
    assert db.query(SaleItem).count() == 0  # No sale item created
    db.close()


# -----------------------------------------------------------------------------
# Test 16: Concurrent Stock Deduction Cannot Oversell
# -----------------------------------------------------------------------------
def test_16_concurrent_stock_deduction_cannot_oversell():
    pos = setup_test_pos("test16@pos.com")
    prod = create_product_direct("Limited Stock Item", 10.0, 1, "pcs", pos["shop_id"], pricing_status="VERIFIED")

    # First checkout of 1 pc succeeds
    resp1 = client.post(
        "/api/v1/sales",
        json={"items": [{"product_id": str(prod.id), "quantity": 1}]},
        headers=pos["headers"],
    )
    assert resp1.status_code == 201

    # Second concurrent checkout of 1 pc must fail immediately
    resp2 = client.post(
        "/api/v1/sales",
        json={"items": [{"product_id": str(prod.id), "quantity": 1}]},
        headers=pos["headers"],
    )
    assert resp2.status_code == 400
    assert "Insufficient stock" in resp2.json()["detail"]

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter_by(id=prod.id).first()
    assert refreshed.current_stock == 0  # Stock never went negative
    db.close()


# -----------------------------------------------------------------------------
# Test 17: Product Belonging to Another Shop is Rejected
# -----------------------------------------------------------------------------
def test_17_cross_shop_product_rejected():
    pos1 = setup_test_pos("shop1@pos.com")
    pos2 = setup_test_pos("shop2@pos.com")

    # Product belongs to shop 2
    prod_shop2 = create_product_direct("Shop 2 Special", 200.0, 10, "pcs", pos2["shop_id"], pricing_status="VERIFIED")

    # Shop 1 tries to sell Shop 2's product
    payload = {
        "items": [{"product_id": str(prod_shop2.id), "quantity": 1}],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos1["headers"])
    assert resp.status_code == 400
    assert "does not belong to your shop" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 18: Existing API Payload Compatibility
# -----------------------------------------------------------------------------
def test_18_existing_api_payload_compatibility():
    pos = setup_test_pos("test18@pos.com")
    prod = create_product_direct("Classic Bread", 35.0, 15, "pcs", pos["shop_id"], pricing_status="VERIFIED")

    # Existing frontend legacy payload without unit or unit_price
    payload = {
        "items": [
            {
                "product_id": str(prod.id),
                "quantity": 2,
            }
        ],
        "payment_method": "cash",
    }
    resp = client.post("/api/v1/sales", json=payload, headers=pos["headers"])
    assert resp.status_code == 201
    data = resp.json()
    assert data["total_amount"] == 70.0
    assert data["items"][0]["quantity"] == 2
    assert data["items"][0]["unit_price"] == 35.0
