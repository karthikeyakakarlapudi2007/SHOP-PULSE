"""
Comprehensive OCR Invoice & Purchase Ingestion Pricing Integration Tests (Stage 4C).

Validates:
- Supplier rate normalization via calculate_purchase_cost()
- Statutory MRP ceiling enforcement
- Retail selling price protection on VERIFIED products
- Package size and multi-unit rate interpretation
- Promotional goods (10+1, zero-rate lines)
- Duplicate invoice detection and atomic rollbacks
- Receipt fidelity and gross margin reporting harmony
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
from db.models.supplier import Supplier
from db.models.purchase import Purchase
from db.models.purchase_item import PurchaseItem
from api.deps import get_db
from services.invoice import resolve_item_arithmetic_py
from services.pricing_engine import calculate_purchase_cost, evaluate_mrp_ceiling

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


def setup_test_shop_and_supplier(email: str = "invoice_tester@example.com"):
    """Helper to create authenticated user, shop, and supplier."""
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    shop_res = client.post(
        "/api/v1/shops",
        json={
            "shop_name": "Test Invoice Kirana",
            "owner_name": "Kirana Merchant",
            "business_type": "Grocery/Kirana",
            "location": "Central Market",
        },
        headers=headers,
    )
    shop_id = uuid.UUID(shop_res.json()["id"])

    sup_res = client.post(
        "/api/v1/suppliers",
        json={
            "supplier_name": "Metro Cash & Carry",
            "phone": "9876543210",
        },
        headers=headers,
    )
    supplier_id = uuid.UUID(sup_res.json()["id"])

    return {"headers": headers, "shop_id": shop_id, "supplier_id": supplier_id}


def create_product_direct(
    name: str,
    selling_price: float,
    current_stock: float,
    unit: str,
    shop_id: uuid.UUID,
    purchase_price: float = 0.0,
    mrp: float = None,
    price_basis_quantity: float = 1.0,
    price_basis_unit: str = None,
    pricing_status: str = "VERIFIED",
) -> Product:
    """Helper to inject catalog product with exact attributes."""
    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name=name,
        category="Groceries",
        selling_price=selling_price,
        purchase_price=purchase_price,
        mrp=mrp,
        current_stock=current_stock,
        unit=unit,
        price_basis_quantity=price_basis_quantity,
        price_basis_unit=price_basis_unit or unit,
        pricing_status=pricing_status,
        is_active=True,
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    db.close()
    return prod


# =============================================================================
# SCENARIO 1: Normalized Rice Cost (5 bags of 10kg @ ₹800/bag -> ₹80/kg)
# =============================================================================
def test_1_normalized_rice_cost():
    env = setup_test_shop_and_supplier("sc1_rice@test.com")
    prod = create_product_direct(
        "Sona Masoori Rice", selling_price=95.0, current_stock=100.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=70.0, price_basis_quantity=1.0, price_basis_unit="kg",
    )

    confirm_payload = {
        "invoice_number": "INV-RICE-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Sona Masoori Rice",
                "matched_product_id": str(prod.id),
                "quantity": 50.0,
                "unit": "kg",
                "purchase_price": 800.0,
                "price_basis_quantity": 10.0,
                "price_basis_unit": "kg",
                "line_amount": 4000.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 150.0
    assert refreshed_prod.purchase_price == 80.0  # ₹800 / 10kg = ₹80/kg
    db.close()


# =============================================================================
# SCENARIO 2: Normalized Spice Cost (500g @ ₹30 per 100g -> ₹0.30/g)
# =============================================================================
def test_2_normalized_spice_cost():
    env = setup_test_shop_and_supplier("sc2_spices@test.com")
    prod = create_product_direct(
        "Red Chilli Powder", selling_price=45.0, current_stock=200.0, unit="g",
        shop_id=env["shop_id"], purchase_price=0.25, price_basis_quantity=100.0, price_basis_unit="g",
    )

    confirm_payload = {
        "invoice_number": "INV-SPICE-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Red Chilli Powder",
                "matched_product_id": str(prod.id),
                "quantity": 500.0,
                "unit": "g",
                "purchase_price": 30.0,
                "price_basis_quantity": 100.0,
                "price_basis_unit": "g",
                "line_amount": 150.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 700.0
    assert refreshed_prod.purchase_price == 0.30  # ₹30 / 100g = ₹0.30/g
    db.close()


# =============================================================================
# SCENARIO 3: Normalized Oil Cost (15L tin @ ₹1800 -> ₹120/L)
# =============================================================================
def test_3_normalized_oil_cost():
    env = setup_test_shop_and_supplier("sc3_oil@test.com")
    prod = create_product_direct(
        "Gemini Sunflower Oil", selling_price=140.0, current_stock=10.0, unit="L",
        shop_id=env["shop_id"], purchase_price=110.0, price_basis_quantity=1.0, price_basis_unit="L",
    )

    confirm_payload = {
        "invoice_number": "INV-OIL-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Gemini Sunflower Oil",
                "matched_product_id": str(prod.id),
                "quantity": 15.0,
                "unit": "L",
                "purchase_price": 1800.0,
                "price_basis_quantity": 15.0,
                "price_basis_unit": "L",
                "line_amount": 1800.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 25.0
    assert refreshed_prod.purchase_price == 120.0  # ₹1800 / 15L = ₹120/L
    db.close()


# =============================================================================
# SCENARIO 4: Normalized Biscuit Cost (24 packets @ ₹240 per 12 pkts -> ₹20/pkt)
# =============================================================================
def test_4_normalized_biscuit_cost():
    env = setup_test_shop_and_supplier("sc4_biscuit@test.com")
    prod = create_product_direct(
        "Parle-G Gold Biscuits", selling_price=25.0, current_stock=12.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=18.0, price_basis_quantity=1.0, price_basis_unit="packet",
    )

    confirm_payload = {
        "invoice_number": "INV-PARLE-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Parle-G Gold Biscuits",
                "matched_product_id": str(prod.id),
                "quantity": 24.0,
                "unit": "packet",
                "purchase_price": 240.0,
                "price_basis_quantity": 12.0,
                "price_basis_unit": "packet",
                "line_amount": 480.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 36.0
    assert refreshed_prod.purchase_price == 20.0  # ₹240 / 12 pkts = ₹20/pkt
    db.close()


# =============================================================================
# SCENARIO 5: Normalized Egg Cost (30 eggs @ ₹480 per 12 pcs -> ₹40/pc)
# =============================================================================
def test_5_normalized_egg_cost():
    env = setup_test_shop_and_supplier("sc5_eggs@test.com")
    prod = create_product_direct(
        "Farm Fresh Eggs", selling_price=7.0, current_stock=50.0, unit="pcs",
        shop_id=env["shop_id"], purchase_price=5.0, price_basis_quantity=1.0, price_basis_unit="pcs",
    )

    confirm_payload = {
        "invoice_number": "INV-EGGS-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Farm Fresh Eggs",
                "matched_product_id": str(prod.id),
                "quantity": 30.0,
                "unit": "pcs",
                "purchase_price": 480.0,
                "price_basis_quantity": 12.0,
                "price_basis_unit": "pcs",
                "line_amount": 1200.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 80.0
    assert refreshed_prod.purchase_price == 40.0  # ₹480 / 12 pcs = ₹40/pc
    db.close()


# =============================================================================
# SCENARIO 6: Selling Price Protected on VERIFIED Product
# =============================================================================
def test_6_selling_price_protected_on_verified_product():
    env = setup_test_shop_and_supplier("sc6_protect@test.com")
    prod = create_product_direct(
        "Basmati Rice Premium 1kg", selling_price=120.0, current_stock=20.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=90.0, pricing_status="VERIFIED",
    )

    # Invoiced line contains selling_price=95.0, but update_selling_price=False
    confirm_payload = {
        "invoice_number": "INV-BASMATI-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Basmati Rice Premium 1kg",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "kg",
                "purchase_price": 85.0,
                "selling_price": 95.0,
                "update_selling_price": False,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 30.0
    assert refreshed_prod.purchase_price == 85.0  # Restocked purchase price updated
    assert refreshed_prod.selling_price == 120.0  # Strictly protected at ₹120!
    db.close()


# =============================================================================
# SCENARIO 7: Explicit Selling Price Override
# =============================================================================
def test_7_explicit_selling_price_override():
    env = setup_test_shop_and_supplier("sc7_override@test.com")
    prod = create_product_direct(
        "Toor Dal Premium 1kg", selling_price=150.0, current_stock=15.0, unit="kg",
        shop_id=env["shop_id"], mrp=180.0, pricing_status="VERIFIED",
    )

    confirm_payload = {
        "invoice_number": "INV-DAL-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Toor Dal Premium 1kg",
                "matched_product_id": str(prod.id),
                "quantity": 20.0,
                "unit": "kg",
                "purchase_price": 130.0,
                "selling_price": 160.0,
                "update_selling_price": True,  # Explicit override
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.selling_price == 160.0  # Successfully updated with explicit flag
    db.close()


# =============================================================================
# SCENARIO 8: Selling Price Exceeds MRP Ceiling Rejected
# =============================================================================
def test_8_selling_price_exceeds_mrp_rejected():
    env = setup_test_shop_and_supplier("sc8_mrp@test.com")
    prod = create_product_direct(
        "Packaged Coffee 200g", selling_price=90.0, current_stock=10.0, unit="packet",
        shop_id=env["shop_id"], mrp=100.0, pricing_status="VERIFIED",
    )

    confirm_payload = {
        "invoice_number": "INV-COFFEE-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Packaged Coffee 200g",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "packet",
                "purchase_price": 80.0,
                "selling_price": 110.0,  # Exceeds statutory MRP ₹100!
                "update_selling_price": True,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 400
    assert "exceeds statutory MRP ceiling" in res.json()["detail"]


# =============================================================================
# SCENARIO 9: New Product Basis Initialized (status='NEEDS_REVIEW')
# =============================================================================
def test_9_new_product_basis_initialized():
    env = setup_test_shop_and_supplier("sc9_newprod@test.com")

    confirm_payload = {
        "invoice_number": "INV-QUINOA-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Organic White Quinoa 500g",
                "quantity": 10.0,
                "unit": "packet",
                "purchase_price": 140.0,
                "selling_price": 180.0,
                "mrp": 200.0,
                "price_basis_quantity": 1.0,
                "price_basis_unit": "packet",
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    new_prod = db.query(Product).filter(Product.shop_id == env["shop_id"], Product.name == "Organic White Quinoa 500g").first()
    assert new_prod is not None
    assert new_prod.pricing_status == "NEEDS_REVIEW"
    assert new_prod.price_basis_quantity == 1.0
    assert new_prod.price_basis_unit == "packet"
    assert new_prod.current_stock == 10.0
    assert new_prod.purchase_price == 140.0
    assert new_prod.selling_price == 180.0
    db.close()


# =============================================================================
# SCENARIO 10: Tax-Inclusive Invoice Line Arithmetic
# =============================================================================
def test_10_tax_inclusive_invoice_line():
    arith = resolve_item_arithmetic_py(
        qty=10.0,
        rate=100.0,
        total=1180.0,
        tax=180.0,
        discount=0.0,
        price_basis_quantity=1.0,
    )
    assert arith["status"] == "VERIFIED"
    assert arith["line_total"] == 1180.0
    assert len(arith["issues"]) == 0


# =============================================================================
# SCENARIO 11: Tax-Exclusive Invoice Line Arithmetic
# =============================================================================
def test_11_tax_exclusive_invoice_line():
    arith = resolve_item_arithmetic_py(
        qty=5.0,
        rate=200.0,
        total=1050.0,
        tax=50.0,
        discount=0.0,
        price_basis_quantity=1.0,
    )
    assert arith["status"] == "VERIFIED"
    assert arith["line_total"] == 1050.0
    assert len(arith["issues"]) == 0


# =============================================================================
# SCENARIO 12: Line Discount Applied Arithmetic
# =============================================================================
def test_12_line_discount_applied():
    arith = resolve_item_arithmetic_py(
        qty=2.0,
        rate=100.0,
        total=180.0,
        tax=0.0,
        discount=20.0,
        price_basis_quantity=1.0,
    )
    assert arith["status"] == "VERIFIED"
    assert arith["line_total"] == 180.0
    assert len(arith["issues"]) == 0


# =============================================================================
# SCENARIO 13: Promotional Free Units (10+1 Scheme)
# =============================================================================
def test_13_promotional_free_units_10_plus_1():
    env = setup_test_shop_and_supplier("sc13_freeunits@test.com")
    prod = create_product_direct(
        "Britannia Milk Bikis", selling_price=35.0, current_stock=20.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=28.0,
    )

    confirm_payload = {
        "invoice_number": "INV-SCHEME-001",
        "supplier_id": str(env["supplier_id"]),
        "confirm_free_units": True,
        "items": [
            {
                "name": "Britannia Milk Bikis",
                "matched_product_id": str(prod.id),
                "quantity": 11.0,
                "paid_quantity": 10.0,
                "free_quantity": 1.0,
                "unit": "packet",
                "purchase_price": 30.0,
                "line_amount": 300.0,  # 10 paid * ₹30 = ₹300
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["total_units"] == 11.0
    assert data["total_amount"] == 300.0

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 31.0  # 20 + 11 received
    assert refreshed_prod.purchase_price == 30.0
    db.close()


# =============================================================================
# SCENARIO 14: Zero-Rate Promotional Line (Sample / Free Goods)
# =============================================================================
def test_14_zero_rate_promotional_line():
    env = setup_test_shop_and_supplier("sc14_zerorate@test.com")
    prod = create_product_direct(
        "Free Promotional Biscuit Pack", selling_price=10.0, current_stock=5.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=8.0,
    )

    confirm_payload = {
        "invoice_number": "INV-SAMPLE-001",
        "supplier_id": str(env["supplier_id"]),
        "confirm_free_units": True,
        "items": [
            {
                "name": "Free Promotional Biscuit Pack",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "packet",
                "purchase_price": 0.0,
                "is_free_item": True,
                "line_amount": 0.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 15.0  # 5 + 10 received
    assert refreshed_prod.purchase_price == 8.0  # Not overwritten by 0.00!
    db.close()


# =============================================================================
# SCENARIO 15: Duplicate Invoice Conflict
# =============================================================================
def test_15_duplicate_invoice_conflict():
    env = setup_test_shop_and_supplier("sc15_duplicate@test.com")
    prod = create_product_direct(
        "Sunfeast Dark Fantasy", selling_price=40.0, current_stock=10.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=30.0,
    )

    confirm_payload = {
        "invoice_number": "INV-DUP-100",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Sunfeast Dark Fantasy",
                "matched_product_id": str(prod.id),
                "quantity": 5.0,
                "unit": "packet",
                "purchase_price": 30.0,
                "line_amount": 150.0,
            }
        ],
    }

    # First confirmation succeeds
    res1 = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res1.status_code == 201, res1.text

    # Second confirmation with exact same supplier invoice number must fail with 409 Conflict
    res2 = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res2.status_code == 409
    assert "already added to stock" in res2.json()["detail"]


# =============================================================================
# SCENARIO 16: Incompatible Units Rejection
# =============================================================================
def test_16_incompatible_units_rejection():
    env = setup_test_shop_and_supplier("sc16_incompat@test.com")
    prod = create_product_direct(
        "Kachi Ghani Mustard Oil", selling_price=160.0, current_stock=20.0, unit="L",
        shop_id=env["shop_id"], purchase_price=130.0,
    )

    # Attempt to restock a volume product (L) with a mass unit (kg)
    confirm_payload = {
        "invoice_number": "INV-UNITMISMATCH-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Kachi Ghani Mustard Oil",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "kg",
                "purchase_price": 130.0,
                "line_amount": 1300.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 400
    assert "cannot be converted" in res.json()["detail"] or "different families" in res.json()["detail"]


# =============================================================================
# SCENARIO 17: Atomic Rollback on Error
# =============================================================================
def test_17_atomic_rollback_on_error():
    env = setup_test_shop_and_supplier("sc17_rollback@test.com")
    prod1 = create_product_direct(
        "Valid Product A", selling_price=50.0, current_stock=10.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=40.0,
    )

    # Multi-item invoice: Item 1 valid, Item 2 invalid (new product with missing selling price)
    confirm_payload = {
        "invoice_number": "INV-ROLLBACK-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Valid Product A",
                "matched_product_id": str(prod1.id),
                "quantity": 5.0,
                "unit": "packet",
                "purchase_price": 40.0,
            },
            {
                "name": "Invalid New Product B",
                "quantity": 5.0,
                "unit": "packet",
                "purchase_price": 40.0,
                "selling_price": None,  # Missing selling price causes validation failure
            },
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 400

    db = TestingSessionLocal()
    refreshed_prod1 = db.query(Product).filter(Product.id == prod1.id).first()
    assert refreshed_prod1.current_stock == 10.0  # Stock was NOT changed!
    purchases = db.query(Purchase).filter(Purchase.invoice_number == "INV-ROLLBACK-001").all()
    assert len(purchases) == 0  # No purchase was created
    db.close()


# =============================================================================
# SCENARIO 18: Direct Purchase Normalized
# =============================================================================
def test_18_direct_purchase_normalized():
    env = setup_test_shop_and_supplier("sc18_direct@test.com")
    prod = create_product_direct(
        "Aashirvaad Atta 10kg", selling_price=450.0, current_stock=5.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=35.0, price_basis_quantity=1.0, price_basis_unit="kg",
    )

    purchase_payload = {
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "product_id": str(prod.id),
                "quantity": 50.0,
                "unit": "kg",
                "purchase_price": 380.0,
                "price_basis_quantity": 10.0,
                "price_basis_unit": "kg",
            }
        ],
    }

    res = client.post("/api/v1/purchases", json=purchase_payload, headers=env["headers"])
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["total_amount"] == 1900.0  # (50 / 10) * ₹380 = ₹1900

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.current_stock == 55.0  # 5 + 50
    assert refreshed_prod.purchase_price == 38.0  # ₹380 / 10kg = ₹38/kg
    db.close()


# =============================================================================
# SCENARIO 19: Receipt Fidelity in PurchaseItems
# =============================================================================
def test_19_receipt_fidelity_purchase_items():
    env = setup_test_shop_and_supplier("sc19_fidelity@test.com")
    prod = create_product_direct(
        "Tata Salt 1kg", selling_price=28.0, current_stock=20.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=20.0, mrp=28.0,
    )

    confirm_payload = {
        "invoice_number": "INV-FIDELITY-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Tata Salt 1kg",
                "matched_product_id": str(prod.id),
                "quantity": 25.0,
                "unit": "packet",
                "purchase_price": 21.50,
                "line_amount": 537.50,
                "mrp": 28.0,
                "mrp_source": "INVOICE",
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    purchase = db.query(Purchase).filter(Purchase.invoice_number == "INV-FIDELITY-001").first()
    assert purchase is not None
    assert purchase.total_amount == 537.50

    item = purchase.items[0]
    assert item.quantity == 25.0
    assert item.purchase_price == 21.50
    assert item.line_amount == 537.50
    assert item.mrp == 28.0
    assert item.mrp_source == "INVOICE"
    db.close()


# =============================================================================
# SCENARIO 20: Margin Reporting Harmony
# =============================================================================
def test_20_margin_reporting_harmony():
    env = setup_test_shop_and_supplier("sc20_margin@test.com")
    prod = create_product_direct(
        "Bulk Moong Dal", selling_price=120.0, current_stock=50.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=80.0, price_basis_quantity=1.0, price_basis_unit="kg",
    )

    # Restock with supplier rate ₹900 per 10kg (normalized cost = ₹90/kg)
    confirm_payload = {
        "invoice_number": "INV-MARGIN-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Bulk Moong Dal",
                "matched_product_id": str(prod.id),
                "quantity": 50.0,
                "unit": "kg",
                "purchase_price": 900.0,
                "price_basis_quantity": 10.0,
                "price_basis_unit": "kg",
                "line_amount": 4500.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed_prod = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed_prod.purchase_price == 90.0
    assert refreshed_prod.selling_price == 120.0

    # Theoretical unit margin: ₹120 - ₹90 = ₹30 per kg (25% gross margin)
    unit_margin = refreshed_prod.selling_price - refreshed_prod.purchase_price
    margin_pct = (unit_margin / refreshed_prod.selling_price) * 100
    assert unit_margin == 30.0
    assert margin_pct == 25.0

    # Sell 500g via POS checkout
    sale_payload = {
        "items": [
            {
                "product_id": str(prod.id),
                "quantity": 500.0,
                "unit": "g",
            }
        ],
        "payment_method": "CASH",
    }
    sale_res = client.post("/api/v1/sales", json=sale_payload, headers=env["headers"])
    assert sale_res.status_code == 201, sale_res.text
    sale_data = sale_res.json()
    assert sale_data["total_amount"] == 60.0  # 500g @ ₹120/kg = ₹60.00

    # Line COGS: 500g @ ₹90/kg = ₹45.00
    # Line Gross Profit: ₹60 - ₹45 = ₹15.00
    # Margin %: (15 / 60) * 100 = 25% -> Perfect mathematical harmony!
    cogs = Decimal("0.5") * Decimal(str(refreshed_prod.purchase_price))
    profit = Decimal(str(sale_data["total_amount"])) - cogs
    realized_margin_pct = (profit / Decimal(str(sale_data["total_amount"]))) * Decimal("100")
    assert cogs == Decimal("45.0")
    assert profit == Decimal("15.0")
    assert realized_margin_pct == Decimal("25.0")
    db.close()
