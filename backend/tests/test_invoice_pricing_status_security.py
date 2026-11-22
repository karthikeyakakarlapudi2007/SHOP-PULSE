"""
Stage 4C.1 Remediation Step 1: Product Pricing Status Lifecycle Security Tests.

Verifies:
1. New invoice-created product always receives NEEDS_REVIEW.
2. Client attempts to submit pricing_status='VERIFIED' are safely ignored / cannot promote product.
3. Client attempts to submit pricing_status='NEEDS_REVIEW' cannot control the resulting status.
4. Client attempts to submit pricing_status='WHOLESALE_ONLY' cannot manipulate status.
5. Existing VERIFIED product remains VERIFIED after invoice restocking.
6. Existing NEEDS_REVIEW product remains NEEDS_REVIEW after invoice restocking.
7. Existing INCOMPLETE product remains INCOMPLETE after invoice restocking.
8. Existing WHOLESALE_ONLY product remains WHOLESALE_ONLY after invoice restocking.
9. Purchase-cost normalization continues working.
10. Inventory quantities update correctly.
11. Duplicate invoice protection remains functional.
12. Invoice transaction rollback remains functional.
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
from db.models.purchase import Purchase
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


def setup_test_env(email: str = "status_sec@test.com"):
    """Creates authenticated user, shop, and supplier."""
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    shop_res = client.post(
        "/api/v1/shops",
        json={
            "shop_name": "Security Audit Kirana",
            "owner_name": "Audit Manager",
            "business_type": "Grocery/Kirana",
            "location": "Audit Sector",
        },
        headers=headers,
    )
    shop_id = uuid.UUID(shop_res.json()["id"])

    sup_res = client.post(
        "/api/v1/suppliers",
        json={
            "supplier_name": "Wholesale Distributor Corp",
            "phone": "9998887776",
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
    """Helper to inject catalog product with exact status and pricing attributes."""
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
# 1. New invoice-created product always receives NEEDS_REVIEW
# =============================================================================
def test_1_new_invoice_created_product_always_receives_needs_review():
    env = setup_test_env("sec1_newprod@test.com")

    payload = {
        "invoice_number": "INV-SEC-001",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Unregistered Cold Pressed Mustard Oil 1L",
                "quantity": 10.0,
                "unit": "L",
                "purchase_price": 140.0,
                "selling_price": 180.0,
                "price_basis_quantity": 1.0,
                "price_basis_unit": "L",
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    new_prod = db.query(Product).filter(
        Product.shop_id == env["shop_id"],
        Product.name == "Unregistered Cold Pressed Mustard Oil 1L"
    ).first()
    assert new_prod is not None
    assert new_prod.pricing_status == "NEEDS_REVIEW"
    db.close()


# =============================================================================
# 2. Client attempts to submit pricing_status="VERIFIED" are safely ignored
# =============================================================================
def test_2_client_submitting_verified_safely_ignored_and_remains_needs_review():
    env = setup_test_env("sec2_attack_verified@test.com")

    # Attacker attempts to inject pricing_status="VERIFIED" on a new product
    payload = {
        "invoice_number": "INV-SEC-002",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Maliciously Verified Olive Oil 500ml",
                "quantity": 5.0,
                "unit": "ml",
                "purchase_price": 300.0,
                "selling_price": 400.0,
                "pricing_status": "VERIFIED",  # Exploit attempt
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    new_prod = db.query(Product).filter(
        Product.shop_id == env["shop_id"],
        Product.name == "Maliciously Verified Olive Oil 500ml"
    ).first()
    assert new_prod is not None
    # Must remain NEEDS_REVIEW; client injection cannot promote it!
    assert new_prod.pricing_status == "NEEDS_REVIEW"
    db.close()


# =============================================================================
# 3. Client attempts to submit pricing_status="NEEDS_REVIEW" cannot control status
# =============================================================================
def test_3_client_submitting_needs_review_cannot_control_status():
    env = setup_test_env("sec3_needs_review@test.com")

    payload = {
        "invoice_number": "INV-SEC-003",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Control Product A 1kg",
                "quantity": 10.0,
                "unit": "kg",
                "purchase_price": 50.0,
                "selling_price": 70.0,
                "pricing_status": "NEEDS_REVIEW",
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    new_prod = db.query(Product).filter(
        Product.shop_id == env["shop_id"],
        Product.name == "Control Product A 1kg"
    ).first()
    assert new_prod.pricing_status == "NEEDS_REVIEW"
    db.close()


# =============================================================================
# 4. Client attempts to submit pricing_status="WHOLESALE_ONLY" cannot manipulate status
# =============================================================================
def test_4_client_submitting_wholesale_only_cannot_manipulate_status():
    env = setup_test_env("sec4_wholesale@test.com")

    payload = {
        "invoice_number": "INV-SEC-004",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Commercial Bulk Lentils 50kg",
                "quantity": 50.0,
                "unit": "kg",
                "purchase_price": 3000.0,
                "selling_price": 4000.0,
                "pricing_status": "WHOLESALE_ONLY",  # Attempt to force wholesale classification
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    new_prod = db.query(Product).filter(
        Product.shop_id == env["shop_id"],
        Product.name == "Commercial Bulk Lentils 50kg"
    ).first()
    # New products must always start at NEEDS_REVIEW for manager verification
    assert new_prod.pricing_status == "NEEDS_REVIEW"
    db.close()


# =============================================================================
# 5. Existing VERIFIED product remains VERIFIED after invoice restocking
# =============================================================================
def test_5_existing_verified_product_remains_verified_after_invoice_restocking():
    env = setup_test_env("sec5_stay_verified@test.com")
    prod = create_product_direct(
        "Verified Basmati Rice", selling_price=110.0, current_stock=20.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=80.0, pricing_status="VERIFIED"
    )

    payload = {
        "invoice_number": "INV-SEC-005",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Verified Basmati Rice",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "kg",
                "purchase_price": 85.0,
                "pricing_status": "NEEDS_REVIEW",  # Client attempts to demote verified product
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.current_stock == 30.0
    assert refreshed.purchase_price == 85.0
    assert refreshed.pricing_status == "VERIFIED"  # Intact!
    db.close()


# =============================================================================
# 6. Existing NEEDS_REVIEW product remains NEEDS_REVIEW after invoice restocking
# =============================================================================
def test_6_existing_needs_review_product_remains_needs_review_after_invoice_restocking():
    env = setup_test_env("sec6_stay_needs_review@test.com")
    prod = create_product_direct(
        "Pending Review Soap Pack", selling_price=45.0, current_stock=10.0, unit="pcs",
        shop_id=env["shop_id"], purchase_price=35.0, pricing_status="NEEDS_REVIEW"
    )

    # Client attempts to promote to VERIFIED via restocking
    payload = {
        "invoice_number": "INV-SEC-006",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Pending Review Soap Pack",
                "matched_product_id": str(prod.id),
                "quantity": 15.0,
                "unit": "pcs",
                "purchase_price": 34.0,
                "pricing_status": "VERIFIED",  # Unauthorized elevation attempt
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.current_stock == 25.0
    assert refreshed.purchase_price == 34.0
    # Must NOT be promoted to VERIFIED through restocking!
    assert refreshed.pricing_status == "NEEDS_REVIEW"
    db.close()


# =============================================================================
# 7. Existing INCOMPLETE product remains INCOMPLETE after invoice restocking
# =============================================================================
def test_7_existing_incomplete_product_remains_incomplete_after_invoice_restocking():
    env = setup_test_env("sec7_stay_incomplete@test.com")
    prod = create_product_direct(
        "Incomplete Legacy Sugar", selling_price=0.0, current_stock=5.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=0.0, pricing_status="INCOMPLETE"
    )

    payload = {
        "invoice_number": "INV-SEC-007",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Incomplete Legacy Sugar",
                "matched_product_id": str(prod.id),
                "quantity": 20.0,
                "unit": "kg",
                "purchase_price": 38.0,
                "pricing_status": "VERIFIED",  # Unauthorized elevation attempt
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.current_stock == 25.0
    assert refreshed.purchase_price == 38.0
    # Status remains INCOMPLETE until dedicated manager reconciliation
    assert refreshed.pricing_status == "INCOMPLETE"
    db.close()


# =============================================================================
# 8. Existing WHOLESALE_ONLY product remains WHOLESALE_ONLY after invoice restocking
# =============================================================================
def test_8_existing_wholesale_only_product_remains_wholesale_only_after_invoice_restocking():
    env = setup_test_env("sec8_stay_wholesale@test.com")
    prod = create_product_direct(
        "Wholesale Oil Barrel 200L", selling_price=24000.0, current_stock=2.0, unit="can",
        shop_id=env["shop_id"], purchase_price=20000.0, pricing_status="WHOLESALE_ONLY"
    )

    payload = {
        "invoice_number": "INV-SEC-008",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Wholesale Oil Barrel 200L",
                "matched_product_id": str(prod.id),
                "quantity": 1.0,
                "unit": "can",
                "purchase_price": 20500.0,
                "pricing_status": "VERIFIED",  # Attempt to turn wholesale into retail
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.current_stock == 3.0
    assert refreshed.purchase_price == 20500.0
    assert refreshed.pricing_status == "WHOLESALE_ONLY"  # Protected!
    db.close()


# =============================================================================
# 9. Purchase-cost normalization continues working
# =============================================================================
def test_9_purchase_cost_normalization_continues_working():
    env = setup_test_env("sec9_norm_working@test.com")
    prod = create_product_direct(
        "Bulk Rice Bags", selling_price=90.0, current_stock=50.0, unit="kg",
        shop_id=env["shop_id"], purchase_price=70.0, pricing_status="VERIFIED"
    )

    # 50kg @ ₹800 per 10kg basis -> normalized cost = ₹80.0/kg
    payload = {
        "invoice_number": "INV-SEC-009",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Bulk Rice Bags",
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

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.purchase_price == 80.0  # Server-authoritative normalized rate
    assert refreshed.current_stock == 100.0
    db.close()


# =============================================================================
# 10. Inventory quantities update correctly
# =============================================================================
def test_10_inventory_quantities_update_correctly():
    env = setup_test_env("sec10_inv_qty@test.com")
    prod = create_product_direct(
        "Turmeric Powder", selling_price=60.0, current_stock=100.0, unit="g",
        shop_id=env["shop_id"], purchase_price=40.0, pricing_status="VERIFIED"
    )

    # Ingest 250g
    payload = {
        "invoice_number": "INV-SEC-010",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Turmeric Powder",
                "matched_product_id": str(prod.id),
                "quantity": 250.0,
                "unit": "g",
                "purchase_price": 50.0,
                "price_basis_quantity": 250.0,
                "price_basis_unit": "g",
                "line_amount": 50.0,
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 201, res.text

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.current_stock == 350.0  # 100 + 250
    db.close()


# =============================================================================
# 11. Duplicate invoice protection remains functional
# =============================================================================
def test_11_duplicate_invoice_protection_remains_functional():
    env = setup_test_env("sec11_dup_inv@test.com")
    prod = create_product_direct(
        "Ginger Garlic Paste", selling_price=30.0, current_stock=10.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=20.0, pricing_status="VERIFIED"
    )

    payload = {
        "invoice_number": "INV-SEC-DUP-011",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Ginger Garlic Paste",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "packet",
                "purchase_price": 20.0,
            }
        ],
    }

    # First attempt succeeds
    res1 = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res1.status_code == 201, res1.text

    # Second attempt with same invoice_number must be rejected with 409 Conflict
    res2 = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res2.status_code == 409
    assert "already added to stock" in res2.json()["detail"]


# =============================================================================
# 12. Invoice transaction rollback remains functional
# =============================================================================
def test_12_invoice_transaction_rollback_remains_functional():
    env = setup_test_env("sec12_rollback@test.com")
    prod = create_product_direct(
        "Safe Product Z", selling_price=50.0, current_stock=10.0, unit="packet",
        shop_id=env["shop_id"], purchase_price=40.0, pricing_status="VERIFIED"
    )

    # Multi-item invoice where item 1 is valid, item 2 causes validation failure (missing selling price for new item)
    payload = {
        "invoice_number": "INV-SEC-FAIL-012",
        "supplier_id": str(env["supplier_id"]),
        "items": [
            {
                "name": "Safe Product Z",
                "matched_product_id": str(prod.id),
                "quantity": 10.0,
                "unit": "packet",
                "purchase_price": 40.0,
            },
            {
                "name": "Failing New Product Missing SP",
                "quantity": 5.0,
                "unit": "packet",
                "purchase_price": 30.0,
                "selling_price": None,  # Causes InvoiceValidationError
            },
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=env["headers"])
    assert res.status_code == 400

    db = TestingSessionLocal()
    refreshed = db.query(Product).filter(Product.id == prod.id).first()
    assert refreshed.current_stock == 10.0  # Completely untouched!
    purchases = db.query(Purchase).filter(Purchase.invoice_number == "INV-SEC-FAIL-012").all()
    assert len(purchases) == 0
    db.close()
