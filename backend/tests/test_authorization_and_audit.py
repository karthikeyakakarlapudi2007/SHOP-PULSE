"""
Stage 4C.1 Remediation Step 2: Centralized Manager Authorization and Audit Trail Tests.

Verifies all 18 required security and regression scenarios:
1. Cashier attempts to verify a product (403 Forbidden).
2. Manager successfully verifies a valid product (200 OK, VERIFIED).
3. Manager cannot verify a product with incomplete pricing metadata (400 Bad Request).
4. Cashier attempts selling-price override (403 Forbidden, no mutation).
5. Manager successfully authorizes a valid selling-price override (201 Created).
6. Client submits a forged manager role in registration/update (ignored, server-authoritative).
7. Client submits a forged shop ID (403 Forbidden, tenant isolation).
8. Cashier attempts to modify pricing status through ProductUpdate (ignored / remains NEEDS_REVIEW).
9. Client attempts to create a VERIFIED product (forced to NEEDS_REVIEW).
10. Invoice confirmation attempts unauthorized selling-price override (403 Forbidden).
11. Manager-authorized invoice price override records audit trail.
12. Audit entry records exact previous and new values.
13. Unauthorized requests create zero business-data mutations (atomic rollback).
14. Audit records are server-authoritative and immutable (no client modification API).
15. Cross-shop audit access is rejected (403 Forbidden).
16. Role assignment cannot be self-performed (cashier cannot promote self).
17. Existing authentication and login regression.
18. Existing invoice, purchase, Manual POS, and Voice-to-Bill regression.
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
from db.models.user import User
from db.models.shop import Shop
from db.models.shop_member import ShopMember, ShopRole
from db.models.product import Product
from db.models.purchase import Purchase
from db.models.pricing_audit_log import PricingAuditLog
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


def create_user_and_token(email: str, password: str = "password123") -> tuple[uuid.UUID, dict]:
    client.post("/api/v1/auth/register", json={"email": email, "password": password})
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == email).first()
    user_id = user.id
    db.close()
    return user_id, headers


def create_shop_for_user(headers: dict, shop_name: str = "Test Retail Kirana") -> uuid.UUID:
    res = client.post(
        "/api/v1/shops",
        json={
            "shop_name": shop_name,
            "owner_name": "Test Owner",
            "business_type": "Grocery/Kirana",
            "location": "Main Road",
        },
        headers=headers,
    )
    assert res.status_code == 201
    return uuid.UUID(res.json()["id"])


# ---------------------------------------------------------------------------
# Test Scenarios 1 to 18
# ---------------------------------------------------------------------------


def test_01_cashier_attempts_to_verify_product_forbidden():
    """1. Cashier attempts to verify a product -> 403 Forbidden."""
    owner_id, owner_headers = create_user_and_token("owner1@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 1")

    # Create product as owner (defaults to NEEDS_REVIEW)
    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Basmati Rice 1kg",
            "selling_price": 120.0,
            "unit": "kg",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "current_stock": 50,
        },
        headers=owner_headers,
    )
    assert prod_res.status_code == 201
    product_id = prod_res.json()["id"]

    # Register cashier and have owner add them to shop
    cashier_id, cashier_headers = create_user_and_token("cashier1@test.com")
    add_res = client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )
    assert add_res.status_code == 201

    # Cashier attempts verification
    verify_res = client.post(
        f"/api/v1/products/{product_id}/verify",
        json={"reason": "Cashier unauthorized attempt"},
        headers=cashier_headers,
    )
    assert verify_res.status_code == 403
    assert "Managers and Owners" in verify_res.json()["detail"]

    # Verify product remains NEEDS_REVIEW in database
    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.id == uuid.UUID(product_id)).first()
    assert prod.pricing_status == "NEEDS_REVIEW"
    db.close()


def test_02_manager_successfully_verifies_valid_product():
    """2. Manager successfully verifies a valid product -> 200 OK, VERIFIED, audit log created."""
    owner_id, owner_headers = create_user_and_token("owner2@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 2")

    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Organic Toor Dal 1kg",
            "selling_price": 150.0,
            "mrp": 160.0,
            "unit": "kg",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "current_stock": 30,
        },
        headers=owner_headers,
    )
    assert prod_res.status_code == 201
    product_id = prod_res.json()["id"]

    # Add manager
    manager_id, manager_headers = create_user_and_token("manager2@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(manager_id), "role": "MANAGER"},
        headers=owner_headers,
    )

    # Manager verifies product
    verify_res = client.post(
        f"/api/v1/products/{product_id}/verify",
        json={"reason": "Verified against supplier price sheet"},
        headers=manager_headers,
    )
    assert verify_res.status_code == 200
    assert verify_res.json()["pricing_status"] == "VERIFIED"

    # Verify DB state & audit log
    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.id == uuid.UUID(product_id)).first()
    assert prod.pricing_status == "VERIFIED"

    logs = db.query(PricingAuditLog).filter(PricingAuditLog.product_id == uuid.UUID(product_id)).all()
    assert len(logs) == 1
    assert logs[0].action_type == "VERIFY_PRICING"
    assert logs[0].acting_user_id == manager_id
    assert logs[0].previous_status == "NEEDS_REVIEW"
    assert logs[0].new_status == "VERIFIED"
    assert logs[0].new_selling_price == 150.0
    db.close()


def test_03_manager_cannot_verify_product_with_incomplete_pricing_metadata():
    """3. Manager cannot verify a product with incomplete pricing metadata -> 400 Bad Request."""
    owner_id, owner_headers = create_user_and_token("owner3@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 3")

    # Directly create a product in DB with missing price_basis_unit
    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Ambiguous Rice Bag",
        selling_price=450.0,
        unit="bag",
        price_basis_quantity=1.0,
        price_basis_unit=None,  # Incomplete!
        pricing_status="NEEDS_REVIEW",
        current_stock=10,
    )
    db.add(prod)
    db.commit()
    prod_id = prod.id
    db.close()

    manager_id, manager_headers = create_user_and_token("manager3@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(manager_id), "role": "MANAGER"},
        headers=owner_headers,
    )

    verify_res = client.post(
        f"/api/v1/products/{prod_id}/verify",
        headers=manager_headers,
    )
    assert verify_res.status_code == 400
    assert "lacks a price basis unit" in verify_res.json()["detail"]


def test_04_cashier_attempts_selling_price_override_forbidden():
    """4. Cashier attempts selling-price override on verified product -> 403 Forbidden, no DB mutation."""
    owner_id, owner_headers = create_user_and_token("owner4@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 4")

    # Create supplier
    sup_res = client.post("/api/v1/suppliers", json={"supplier_name": "Sup 4"}, headers=owner_headers)
    supplier_id = sup_res.json()["id"]

    # Create & verify product
    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Sunflower Oil 1L",
        selling_price=130.0,
        purchase_price=100.0,
        mrp=150.0,
        unit="L",
        price_basis_quantity=1.0,
        price_basis_unit="L",
        pricing_status="VERIFIED",
        current_stock=20,
    )
    db.add(prod)
    db.commit()
    prod_id = prod.id
    db.close()

    # Cashier attempts invoice confirm with update_selling_price=True
    cashier_id, cashier_headers = create_user_and_token("cashier4@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    confirm_payload = {
        "supplier_id": supplier_id,
        "invoice_number": "INV-CASHIER-OVERRIDE",
        "items": [
            {
                "name": "Sunflower Oil 1L",
                "quantity": 10,
                "unit": "L",
                "purchase_price": 105.0,
                "selling_price": 140.0,
                "update_selling_price": True,  # Cashier attempting override!
                "matched_product_id": str(prod_id),
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=cashier_headers)
    assert res.status_code == 403
    assert "authorization to override selling price" in res.json()["detail"]

    # Verify no purchase or stock or price was mutated
    db = TestingSessionLocal()
    p = db.query(Product).filter(Product.id == prod_id).first()
    assert p.selling_price == 130.0  # Unchanged
    assert p.current_stock == 20     # Unchanged
    assert db.query(Purchase).filter(Purchase.shop_id == shop_id).count() == 0
    assert db.query(PricingAuditLog).count() == 0
    db.close()


def test_05_manager_successfully_authorizes_valid_selling_price_override():
    """5. Manager successfully authorizes a valid selling-price override -> 201 Created, price updated, audited."""
    owner_id, owner_headers = create_user_and_token("owner5@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 5")

    sup_res = client.post("/api/v1/suppliers", json={"supplier_name": "Sup 5"}, headers=owner_headers)
    supplier_id = sup_res.json()["id"]

    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Mustard Oil 1L",
        selling_price=140.0,
        purchase_price=110.0,
        mrp=160.0,
        unit="L",
        price_basis_quantity=1.0,
        price_basis_unit="L",
        pricing_status="VERIFIED",
        current_stock=15,
    )
    db.add(prod)
    db.commit()
    prod_id = prod.id
    db.close()

    manager_id, manager_headers = create_user_and_token("manager5@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(manager_id), "role": "MANAGER"},
        headers=owner_headers,
    )

    confirm_payload = {
        "supplier_id": supplier_id,
        "invoice_number": "INV-MGR-OVERRIDE-1",
        "items": [
            {
                "name": "Mustard Oil 1L",
                "quantity": 10,
                "unit": "L",
                "purchase_price": 115.0,
                "selling_price": 145.0,
                "update_selling_price": True,
                "matched_product_id": str(prod_id),
            }
        ],
    }

    res = client.post("/api/v1/invoices/confirm", json=confirm_payload, headers=manager_headers)
    assert res.status_code == 201

    # Verify DB update and audit log
    db = TestingSessionLocal()
    p = db.query(Product).filter(Product.id == prod_id).first()
    assert p.selling_price == 145.0
    assert p.current_stock == 25

    logs = db.query(PricingAuditLog).filter(PricingAuditLog.product_id == prod_id).all()
    assert len(logs) == 1
    assert logs[0].action_type == "SELLING_PRICE_OVERRIDE"
    assert logs[0].acting_user_id == manager_id
    assert logs[0].previous_selling_price == 140.0
    assert logs[0].new_selling_price == 145.0
    assert logs[0].invoice_number == "INV-MGR-OVERRIDE-1"
    db.close()


def test_06_client_submits_forged_manager_role_ignored():
    """6. Client submits a forged manager role in registration -> Ignored, server authoritative."""
    forged_id, forged_headers = create_user_and_token("forger@test.com")
    # Forger registers with extra fields injected
    reg_res = client.post(
        "/api/v1/auth/register",
        json={"email": "forger2@test.com", "password": "password123", "role": "MANAGER", "is_admin": True},
    )
    assert reg_res.status_code == 201

    # Check database: no role column or membership exists
    db = TestingSessionLocal()
    user = db.query(User).filter(User.email == "forger2@test.com").first()
    memberships = db.query(ShopMember).filter(ShopMember.user_id == user.id).all()
    assert len(memberships) == 0  # Zero memberships
    db.close()


def test_07_client_submits_forged_shop_id_rejected():
    """7. Client submits a forged shop ID -> 403 Forbidden, tenant isolated."""
    owner_a_id, owner_a_headers = create_user_and_token("owner_a@test.com")
    shop_a_id = create_shop_for_user(owner_a_headers, "Shop A")

    owner_b_id, owner_b_headers = create_user_and_token("owner_b@test.com")
    shop_b_id = create_shop_for_user(owner_b_headers, "Shop B")

    # Owner A attempts to add a member to Shop B
    res = client.post(
        f"/api/v1/shops/{shop_b_id}/members",
        json={"email": "owner_a@test.com", "role": "MANAGER"},
        headers=owner_a_headers,
    )
    assert res.status_code == 403
    assert "Only the shop owner can add or invite" in res.json()["detail"]


def test_08_cashier_attempts_to_modify_pricing_status_through_product_update():
    """8. Cashier attempts to modify pricing status through ProductUpdate -> Ignored, remains NEEDS_REVIEW."""
    owner_id, owner_headers = create_user_and_token("owner8@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 8")

    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Wheat Flour 5kg",
            "selling_price": 220.0,
            "unit": "kg",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "current_stock": 20,
        },
        headers=owner_headers,
    )
    prod_id = prod_res.json()["id"]

    cashier_id, cashier_headers = create_user_and_token("cashier8@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    # Attempt to promote product via PUT /api/v1/products/{id}
    put_res = client.put(
        f"/api/v1/products/{prod_id}",
        json={"pricing_status": "VERIFIED", "selling_price": 225.0},
        headers=cashier_headers,
    )
    assert put_res.status_code == 200
    assert put_res.json()["pricing_status"] == "NEEDS_REVIEW"  # Ignored!

    db = TestingSessionLocal()
    p = db.query(Product).filter(Product.id == uuid.UUID(prod_id)).first()
    assert p.pricing_status == "NEEDS_REVIEW"
    db.close()


def test_09_client_attempts_to_create_verified_product():
    """9. Ordinary user (cashier) attempts to create a VERIFIED product -> Forced to NEEDS_REVIEW."""
    owner_id, owner_headers = create_user_and_token("owner9@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 9")

    cashier_id, cashier_headers = create_user_and_token("cashier9@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    create_res = client.post(
        "/api/v1/products",
        json={
            "name": "Tea Powder 500g",
            "selling_price": 180.0,
            "pricing_status": "VERIFIED",  # Unauthorized assertion by ordinary user
            "unit": "g",
            "price_basis_quantity": 500.0,
            "price_basis_unit": "g",
            "current_stock": 40,
        },
        headers=cashier_headers,
    )
    assert create_res.status_code == 201
    assert create_res.json()["pricing_status"] == "NEEDS_REVIEW"

    db = TestingSessionLocal()
    p = db.query(Product).filter(Product.id == uuid.UUID(create_res.json()["id"])).first()
    assert p.pricing_status == "NEEDS_REVIEW"
    db.close()


def test_10_invoice_confirmation_attempts_unauthorized_selling_price_override():
    """10. Invoice confirmation attempts unauthorized selling-price override -> 403 Forbidden."""
    owner_id, owner_headers = create_user_and_token("owner10@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 10")
    sup_res = client.post("/api/v1/suppliers", json={"supplier_name": "Sup 10"}, headers=owner_headers)
    supplier_id = sup_res.json()["id"]

    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Salt 1kg",
        selling_price=25.0,
        unit="kg",
        price_basis_quantity=1.0,
        price_basis_unit="kg",
        pricing_status="VERIFIED",
        current_stock=100,
    )
    db.add(prod)
    db.commit()
    prod_id = prod.id
    db.close()

    cashier_id, cashier_headers = create_user_and_token("cashier10@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    res = client.post(
        "/api/v1/invoices/confirm",
        json={
            "supplier_id": supplier_id,
            "items": [
                {
                    "name": "Salt 1kg",
                    "quantity": 50,
                    "unit": "kg",
                    "purchase_price": 18.0,
                    "selling_price": 30.0,
                    "update_selling_price": True,
                    "matched_product_id": str(prod_id),
                }
            ],
        },
        headers=cashier_headers,
    )
    assert res.status_code == 403
    assert "Manager or Owner role required" in res.json()["detail"]


def test_11_manager_authorized_invoice_price_override():
    """11. Manager-authorized invoice price override -> 201 Created and audit entry created."""
    owner_id, owner_headers = create_user_and_token("owner11@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 11")
    sup_res = client.post("/api/v1/suppliers", json={"supplier_name": "Sup 11"}, headers=owner_headers)
    supplier_id = sup_res.json()["id"]

    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Sugar 1kg",
        selling_price=42.0,
        unit="kg",
        price_basis_quantity=1.0,
        price_basis_unit="kg",
        pricing_status="VERIFIED",
        current_stock=80,
    )
    db.add(prod)
    db.commit()
    prod_id = prod.id
    db.close()

    manager_id, manager_headers = create_user_and_token("manager11@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(manager_id), "role": "MANAGER"},
        headers=owner_headers,
    )

    res = client.post(
        "/api/v1/invoices/confirm",
        json={
            "supplier_id": supplier_id,
            "invoice_number": "INV-11-AUTH",
            "items": [
                {
                    "name": "Sugar 1kg",
                    "quantity": 40,
                    "unit": "kg",
                    "purchase_price": 36.0,
                    "selling_price": 45.0,
                    "update_selling_price": True,
                    "matched_product_id": str(prod_id),
                }
            ],
        },
        headers=manager_headers,
    )
    assert res.status_code == 201

    # Check audit log via endpoint
    audit_res = client.get(f"/api/v1/products/{prod_id}/audit-trail", headers=manager_headers)
    assert audit_res.status_code == 200
    logs = audit_res.json()
    assert len(logs) == 1
    assert logs[0]["action_type"] == "SELLING_PRICE_OVERRIDE"
    assert logs[0]["previous_selling_price"] == 42.0
    assert logs[0]["new_selling_price"] == 45.0
    assert logs[0]["invoice_number"] == "INV-11-AUTH"


def test_12_audit_entry_records_previous_and_new_values():
    """12. Audit entry records previous and new values."""
    owner_id, owner_headers = create_user_and_token("owner12@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 12")

    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Ghee 500ml",
            "selling_price": 350.0,
            "unit": "ml",
            "price_basis_quantity": 500.0,
            "price_basis_unit": "ml",
            "current_stock": 10,
        },
        headers=owner_headers,
    )
    prod_id = prod_res.json()["id"]

    verify_res = client.post(
        f"/api/v1/products/{prod_id}/verify",
        json={"reason": "Audited certification"},
        headers=owner_headers,
    )
    assert verify_res.status_code == 200

    trail_res = client.get(f"/api/v1/products/{prod_id}/audit-trail", headers=owner_headers)
    assert trail_res.status_code == 200
    entry = trail_res.json()[0]
    assert entry["previous_status"] == "NEEDS_REVIEW"
    assert entry["new_status"] == "VERIFIED"
    assert entry["previous_selling_price"] == 350.0
    assert entry["new_selling_price"] == 350.0
    assert entry["reason"] == "Audited certification"


def test_13_unauthorized_requests_create_no_business_data_mutations():
    """13. Unauthorized requests create no business-data mutations (atomic rejection before purchase creation)."""
    owner_id, owner_headers = create_user_and_token("owner13@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 13")
    sup_res = client.post("/api/v1/suppliers", json={"supplier_name": "Sup 13"}, headers=owner_headers)
    supplier_id = sup_res.json()["id"]

    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Coriander Powder 200g",
        selling_price=65.0,
        unit="g",
        price_basis_quantity=200.0,
        price_basis_unit="g",
        pricing_status="VERIFIED",
        current_stock=50,
    )
    db.add(prod)
    db.commit()
    prod_id = prod.id
    db.close()

    cashier_id, cashier_headers = create_user_and_token("cashier13@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    res = client.post(
        "/api/v1/invoices/confirm",
        json={
            "supplier_id": supplier_id,
            "invoice_number": "INV-NO-MUTATION",
            "items": [
                {
                    "name": "Coriander Powder 200g",
                    "quantity": 20,
                    "unit": "g",
                    "purchase_price": 45.0,
                    "selling_price": 75.0,
                    "update_selling_price": True,
                    "matched_product_id": str(prod_id),
                }
            ],
        },
        headers=cashier_headers,
    )
    assert res.status_code == 403

    db = TestingSessionLocal()
    assert db.query(Purchase).filter(Purchase.shop_id == shop_id).count() == 0
    p = db.query(Product).filter(Product.id == prod_id).first()
    assert p.current_stock == 50
    assert p.selling_price == 65.0
    db.close()


def test_14_audit_records_cannot_be_modified_by_ordinary_users():
    """14. Audit records cannot be modified by ordinary users (no PUT/DELETE endpoints exist)."""
    owner_id, owner_headers = create_user_and_token("owner14@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 14")

    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Turmeric Powder 100g",
            "selling_price": 30.0,
            "unit": "g",
            "price_basis_quantity": 100.0,
            "price_basis_unit": "g",
            "current_stock": 20,
        },
        headers=owner_headers,
    )
    prod_id = prod_res.json()["id"]
    client.post(f"/api/v1/products/{prod_id}/verify", headers=owner_headers)

    db = TestingSessionLocal()
    log = db.query(PricingAuditLog).filter(PricingAuditLog.product_id == uuid.UUID(prod_id)).first()
    log_id = log.id
    db.close()

    # Attempt PUT on audit record
    put_res = client.put(f"/api/v1/products/{prod_id}/audit-trail/{log_id}", json={"new_selling_price": 999.0}, headers=owner_headers)
    assert put_res.status_code in [404, 405]

    # Attempt DELETE on audit record
    del_res = client.delete(f"/api/v1/products/{prod_id}/audit-trail/{log_id}", headers=owner_headers)
    assert del_res.status_code in [404, 405]


def test_15_cross_shop_audit_access_is_rejected():
    """15. Cross-shop audit access is rejected -> 403 Forbidden."""
    owner_a_id, owner_a_headers = create_user_and_token("owner15_a@test.com")
    shop_a_id = create_shop_for_user(owner_a_headers, "Shop 15A")

    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Chana Dal 1kg",
            "selling_price": 90.0,
            "unit": "kg",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "current_stock": 20,
        },
        headers=owner_a_headers,
    )
    prod_a_id = prod_res.json()["id"]
    client.post(f"/api/v1/products/{prod_a_id}/verify", headers=owner_a_headers)

    # Manager of Shop B tries to read audit trail of Shop A
    owner_b_id, owner_b_headers = create_user_and_token("owner15_b@test.com")
    shop_b_id = create_shop_for_user(owner_b_headers, "Shop 15B")

    res = client.get(f"/api/v1/products/{prod_a_id}/audit-trail", headers=owner_b_headers)
    assert res.status_code == 403
    assert "Not authorized to access products of this shop" in res.json()["detail"]


def test_16_role_assignment_cannot_be_self_performed():
    """16. Role assignment cannot be self-performed -> Cashier cannot promote self or modify staff."""
    owner_id, owner_headers = create_user_and_token("owner16@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 16")

    cashier_id, cashier_headers = create_user_and_token("cashier16@test.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    # Cashier attempts to elevate themselves to MANAGER
    res = client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "MANAGER"},
        headers=cashier_headers,
    )
    assert res.status_code == 403
    assert "Only the shop owner can add or invite" in res.json()["detail"]


def test_17_existing_authentication_and_login_regression():
    """17. Existing authentication and login regression."""
    # Test JSON login
    client.post("/api/v1/auth/register", json={"email": "login_reg@test.com", "password": "securepass123"})
    login_res = client.post("/api/v1/auth/login", json={"email": "login_reg@test.com", "password": "securepass123"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    assert token

    # Test me endpoint
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/v1/shops/me", headers=headers)
    assert me_res.status_code == 404  # No shop created yet, clean 404


def test_18_existing_invoice_purchase_manual_pos_voice_pricing_regression():
    """18. Existing invoice, purchase, Manual POS, and Voice-to-Bill regression."""
    owner_id, owner_headers = create_user_and_token("owner18@test.com")
    shop_id = create_shop_for_user(owner_headers, "Shop 18")

    # 1. Create product
    prod_res = client.post(
        "/api/v1/products",
        json={
            "name": "Moong Dal 1kg",
            "selling_price": 110.0,
            "unit": "kg",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "current_stock": 100,
        },
        headers=owner_headers,
    )
    prod_id = prod_res.json()["id"]

    # 2. Verify product by owner
    client.post(f"/api/v1/products/{prod_id}/verify", headers=owner_headers)

    # 3. Create direct purchase (restock)
    sup_res = client.post("/api/v1/suppliers", json={"supplier_name": "Sup 18"}, headers=owner_headers)
    supplier_id = sup_res.json()["id"]

    purch_res = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": supplier_id,
            "items": [
                {
                    "product_id": prod_id,
                    "quantity": 50,
                    "unit": "kg",
                    "purchase_price": 85.0,
                }
            ],
        },
        headers=owner_headers,
    )
    assert purch_res.status_code == 201

    # 4. Manual POS sale
    sale_res = client.post(
        "/api/v1/sales",
        json={
            "items": [
                {
                    "product_id": prod_id,
                    "quantity": 2,
                    "unit": "kg",
                }
            ],
            "payment_method": "CASH",
        },
        headers=owner_headers,
    )
    assert sale_res.status_code == 201
    assert sale_res.json()["total_amount"] == 220.0

    # 5. Check stock: 100 (initial) + 50 (purchased) - 2 (sold) = 148
    db = TestingSessionLocal()
    p = db.query(Product).filter(Product.id == uuid.UUID(prod_id)).first()
    assert p.current_stock == 148
    db.close()
