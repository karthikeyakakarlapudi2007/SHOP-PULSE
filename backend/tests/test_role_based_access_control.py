"""
Stage 5.3: Role-Based Staff Access Control and Data Isolation Test Suite.

Verifies the 11 backend security scenarios required for Stage 5.3:
1. Owner access to all permitted modules.
2. Manager access to permitted management modules.
3. Cashier access to permitted operational modules.
4. Cashier rejection from purchases (403 Forbidden).
5. Cashier rejection from supplier management (403 Forbidden).
6. Cashier rejection from analytics / insights (403 Forbidden).
7. Cashier rejection from pricing audit logs (403 Forbidden).
8. Manager rejection from owner-only staff management (403 Forbidden).
9. Unauthorized shop access rejection (400/403).
10. Cross-shop data isolation (zero data leakage).
11. Invalid or missing membership rejection (403 Forbidden for inactive members).
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
from db.models.supplier import Supplier
from db.models.purchase import Purchase
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


def create_user_and_token(email: str, password: str = "password123") -> tuple[uuid.UUID, dict]:
    reg_res = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert reg_res.status_code == 201, f"Register failed: {reg_res.text}"
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed: {res.text}"
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
# Setup Helper: Create shop with Owner, Manager, and Cashier
# ---------------------------------------------------------------------------

@pytest.fixture
def shop_setup():
    # 1. Owner & Shop
    owner_id, owner_headers = create_user_and_token("owner@example.com")
    shop_id = create_shop_for_user(owner_headers, "Shop Alpha")

    # 2. Manager
    manager_id, manager_headers = create_user_and_token("manager@example.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(manager_id), "role": "MANAGER"},
        headers=owner_headers,
    )

    # 3. Cashier
    cashier_id, cashier_headers = create_user_and_token("cashier@example.com")
    client.post(
        f"/api/v1/shops/{shop_id}/members",
        json={"user_id": str(cashier_id), "role": "CASHIER"},
        headers=owner_headers,
    )

    # 4. Unaffiliated user
    stranger_id, stranger_headers = create_user_and_token("stranger@example.com")

    # 5. Populate some initial resources in Shop Alpha
    db = TestingSessionLocal()
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name="Basmati Rice 1kg",
        selling_price=120.0,
        purchase_price=90.0,
        mrp=140.0,
        unit="kg",
        price_basis_quantity=1.0,
        price_basis_unit="kg",
        current_stock=50,
        pricing_status="VERIFIED",
        is_active=True,
    )
    sup = Supplier(
        id=uuid.uuid4(),
        shop_id=shop_id,
        supplier_name="Alpha Wholesale Traders",
        phone="9876543210",
    )
    db.add_all([prod, sup])
    db.commit()
    prod_id = prod.id
    sup_id = sup.id

    # Create a purchase
    purch = Purchase(
        id=uuid.uuid4(),
        shop_id=shop_id,
        supplier_id=sup_id,
        invoice_number="INV-ALPHA-01",
        total_amount=900.0,
    )
    # Create a sale
    sale = Sale(
        id=uuid.uuid4(),
        shop_id=shop_id,
        total_amount=120.0,
        payment_method="CASH",
    )
    db.add_all([purch, sale])
    db.commit()
    purch_id = purch.id
    sale_id = sale.id
    db.close()

    return {
        "shop_id": shop_id,
        "owner_id": owner_id,
        "owner_headers": owner_headers,
        "manager_id": manager_id,
        "manager_headers": manager_headers,
        "cashier_id": cashier_id,
        "cashier_headers": cashier_headers,
        "stranger_id": stranger_id,
        "stranger_headers": stranger_headers,
        "prod_id": prod_id,
        "sup_id": sup_id,
        "purch_id": purch_id,
        "sale_id": sale_id,
    }


# ---------------------------------------------------------------------------
# Test 1: Owner access to all permitted modules
# ---------------------------------------------------------------------------

def test_01_owner_access_to_all_permitted_modules(shop_setup):
    s = shop_setup
    h = s["owner_headers"]

    # Dashboard
    res = client.get("/api/v1/dashboard", headers=h)
    assert res.status_code == 200

    # Insights / Analytics
    res = client.get("/api/v1/insights/sales", headers=h)
    assert res.status_code == 200

    # Purchases
    res = client.get("/api/v1/purchases", headers=h)
    assert res.status_code == 200
    assert len(res.json()["items"]) >= 1

    # Suppliers
    res = client.get("/api/v1/suppliers", headers=h)
    assert res.status_code == 200
    assert len(res.json()["items"]) >= 1

    # Products
    res = client.get("/api/v1/products", headers=h)
    assert res.status_code == 200
    assert len(res.json()["items"]) >= 1

    # Sales history
    res = client.get("/api/v1/sales", headers=h)
    assert res.status_code == 200
    assert len(res.json()["items"]) >= 1

    # Search
    res = client.get("/api/v1/search?q=Rice", headers=h)
    assert res.status_code == 200
    assert len(res.json()["products"]) >= 1

    # Staff management
    res = client.get(f"/api/v1/shops/{s['shop_id']}/members", headers=h)
    assert res.status_code == 200
    assert len(res.json()) == 3  # owner, manager, cashier


# ---------------------------------------------------------------------------
# Test 2: Manager access to permitted management modules
# ---------------------------------------------------------------------------

def test_02_manager_access_to_permitted_management_modules(shop_setup):
    s = shop_setup
    h = s["manager_headers"]

    # Dashboard
    res = client.get("/api/v1/dashboard", headers=h)
    assert res.status_code == 200

    # Insights / Analytics
    res = client.get("/api/v1/insights/sales", headers=h)
    assert res.status_code == 200
    res = client.get("/api/v1/insights/inventory", headers=h)
    assert res.status_code == 200

    # Purchases
    res = client.get("/api/v1/purchases", headers=h)
    assert res.status_code == 200

    # Suppliers
    res = client.get("/api/v1/suppliers", headers=h)
    assert res.status_code == 200

    # Products (list, view)
    res = client.get("/api/v1/products", headers=h)
    assert res.status_code == 200

    # Sales history
    res = client.get("/api/v1/sales", headers=h)
    assert res.status_code == 200

    # View staff members (Manager permitted to view)
    res = client.get(f"/api/v1/shops/{s['shop_id']}/members", headers=h)
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Test 3: Cashier access to permitted operational modules
# ---------------------------------------------------------------------------

def test_03_cashier_access_to_permitted_operational_modules(shop_setup):
    s = shop_setup
    h = s["cashier_headers"]

    # 1. Product catalogue listing
    res = client.get("/api/v1/products", headers=h)
    assert res.status_code == 200
    assert len(res.json()["items"]) >= 1

    # 2. Low-stock operational check
    res = client.get("/api/v1/products/low-stock", headers=h)
    assert res.status_code == 200

    # 3. Product creation (forced to PENDING_VERIFICATION)
    create_res = client.post(
        "/api/v1/products",
        json={
            "name": "Tata Salt 1kg",
            "category": "Groceries",
            "selling_price": 28.0,
            "purchase_price": 22.0,
            "mrp": 30.0,
            "unit": "pkt",
            "current_stock": 20,
        },
        headers=h,
    )
    assert create_res.status_code == 201
    assert create_res.json()["pricing_status"] in ("NEEDS_REVIEW", "PENDING_VERIFICATION")

    # 4. POS Sale recording
    sale_res = client.post(
        "/api/v1/sales",
        json={
            "payment_method": "CASH",
            "items": [
                {
                    "product_id": str(s["prod_id"]),
                    "quantity": 2,
                    "unit_price": 120.0,
                }
            ],
        },
        headers=h,
    )
    assert sale_res.status_code == 201

    # 5. Sales history (read permitted for shop POS)
    sales_res = client.get("/api/v1/sales", headers=h)
    assert sales_res.status_code == 200

    # 6. Global search (catalogue and sales)
    search_res = client.get("/api/v1/search?q=Rice", headers=h)
    assert search_res.status_code == 200
    assert len(search_res.json()["products"]) >= 1
    # Cashier MUST NOT receive purchase results through search
    assert search_res.json()["purchases"] == []
    assert search_res.json()["totals"]["purchases"] == 0

    # 7. Notifications
    notif_res = client.get("/api/v1/notifications", headers=h)
    assert notif_res.status_code == 200


# ---------------------------------------------------------------------------
# Test 4: Cashier rejection from purchases
# ---------------------------------------------------------------------------

def test_04_cashier_rejection_from_purchases(shop_setup):
    s = shop_setup
    h = s["cashier_headers"]

    # List purchases -> 403 Forbidden
    res = client.get("/api/v1/purchases", headers=h)
    assert res.status_code == 403
    assert "elevated role" in res.json()["detail"].lower() or "forbidden" in res.json()["detail"].lower()

    # Create purchase -> 403 Forbidden
    res = client.post(
        "/api/v1/purchases",
        json={
            "supplier_id": str(s["sup_id"]),
            "invoice_number": "INV-UNAUTH-01",
            "total_amount": 500.0,
            "items": [
                {
                    "product_id": str(s["prod_id"]),
                    "quantity": 10,
                    "purchase_price": 50.0,
                }
            ],
        },
        headers=h,
    )
    assert res.status_code == 403

    # View purchase by ID -> 403 Forbidden
    res = client.get(f"/api/v1/purchases/{s['purch_id']}", headers=h)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Test 5: Cashier rejection from supplier management
# ---------------------------------------------------------------------------

def test_05_cashier_rejection_from_supplier_management(shop_setup):
    s = shop_setup
    h = s["cashier_headers"]

    # List suppliers -> 403 Forbidden
    res = client.get("/api/v1/suppliers", headers=h)
    assert res.status_code == 403

    # Create supplier -> 403 Forbidden
    res = client.post("/api/v1/suppliers", json={"supplier_name": "Rogue Supplier"}, headers=h)
    assert res.status_code == 403

    # View supplier -> 403 Forbidden
    res = client.get(f"/api/v1/suppliers/{s['sup_id']}", headers=h)
    assert res.status_code == 403

    # Update supplier -> 403 Forbidden
    res = client.put(f"/api/v1/suppliers/{s['sup_id']}", json={"supplier_name": "Updated Supplier"}, headers=h)
    assert res.status_code == 403

    # Delete supplier -> 403 Forbidden
    res = client.delete(f"/api/v1/suppliers/{s['sup_id']}", headers=h)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Test 6: Cashier rejection from analytics / dashboard
# ---------------------------------------------------------------------------

def test_06_cashier_rejection_from_analytics(shop_setup):
    s = shop_setup
    h = s["cashier_headers"]

    # Dashboard management view -> 403 Forbidden
    res = client.get("/api/v1/dashboard", headers=h)
    assert res.status_code == 403

    # Sales insights -> 403 Forbidden
    res = client.get("/api/v1/insights/sales", headers=h)
    assert res.status_code == 403

    # Inventory insights -> 403 Forbidden
    res = client.get("/api/v1/insights/inventory", headers=h)
    assert res.status_code == 403

    # AI narrative insights -> 403 Forbidden
    res = client.get("/api/v1/insights/ai-summary", headers=h)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Test 7: Cashier rejection from pricing audit logs
# ---------------------------------------------------------------------------

def test_07_cashier_rejection_from_pricing_audit_logs(shop_setup):
    s = shop_setup
    h = s["cashier_headers"]

    res = client.get(f"/api/v1/products/{s['prod_id']}/audit-trail", headers=h)
    assert res.status_code == 403
    assert "Managers and Owners" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Test 8: Manager rejection from owner-only staff management & shop profile
# ---------------------------------------------------------------------------

def test_08_manager_rejection_from_owner_only_operations(shop_setup):
    s = shop_setup
    mh = s["manager_headers"]

    # 1. Manager attempts to add a new member -> 403 Forbidden
    new_user_id, _ = create_user_and_token("newstaff@example.com")
    res = client.post(
        f"/api/v1/shops/{s['shop_id']}/members",
        json={"user_id": str(new_user_id), "role": "CASHIER"},
        headers=mh,
    )
    assert res.status_code == 403
    assert "Only the shop owner" in res.json()["detail"]

    # 2. Manager attempts to update shop profile -> 403 Forbidden
    res = client.put(
        f"/api/v1/shops/{s['shop_id']}",
        json={"shop_name": "Hijacked Shop Name"},
        headers=mh,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Test 9: Unauthorized shop access rejection
# ---------------------------------------------------------------------------

def test_09_unauthorized_shop_access_rejection(shop_setup):
    s = shop_setup
    stranger_h = s["stranger_headers"]

    # Stranger has no shop profile
    res = client.get("/api/v1/dashboard", headers=stranger_h)
    assert res.status_code in (400, 403)

    res = client.get("/api/v1/products", headers=stranger_h)
    # Empty list because user has no shop
    assert res.status_code == 200
    assert res.json()["items"] == []

    # Attempting to access Shop Alpha's members directly
    res = client.get(f"/api/v1/shops/{s['shop_id']}/members", headers=stranger_h)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Test 10: Cross-shop data isolation
# ---------------------------------------------------------------------------

def test_10_cross_shop_data_isolation(shop_setup):
    s = shop_setup

    # Create a completely separate Shop Beta with its own Owner and Cashier
    owner_b_id, owner_b_headers = create_user_and_token("owner_b@example.com")
    shop_b_id = create_shop_for_user(owner_b_headers, "Shop Beta")

    # Add Cashier to Shop Beta
    cashier_b_id, cashier_b_headers = create_user_and_token("cashier_b@example.com")
    client.post(
        f"/api/v1/shops/{shop_b_id}/members",
        json={"user_id": str(cashier_b_id), "role": "CASHIER"},
        headers=owner_b_headers,
    )

    # 1. Shop Beta Cashier listing products must NOT see Shop Alpha's products
    res = client.get("/api/v1/products", headers=cashier_b_headers)
    assert res.status_code == 200
    product_names = [p["name"] for p in res.json()["items"]]
    assert "Basmati Rice 1kg" not in product_names

    # 2. Shop Beta Cashier searching "Rice" must get zero hits
    search_res = client.get("/api/v1/search?q=Rice", headers=cashier_b_headers)
    assert search_res.status_code == 200
    assert len(search_res.json()["products"]) == 0

    # 3. Shop Beta Owner accessing Shop Alpha's product by ID -> 403 Forbidden
    res = client.get(f"/api/v1/products/{s['prod_id']}", headers=owner_b_headers)
    assert res.status_code == 403

    # 4. Shop Beta Owner accessing Shop Alpha's purchase by ID -> 403 Forbidden
    res = client.get(f"/api/v1/purchases/{s['purch_id']}", headers=owner_b_headers)
    assert res.status_code == 403

    # 5. Shop Beta Owner accessing Shop Alpha's supplier by ID -> 403 Forbidden
    res = client.get(f"/api/v1/suppliers/{s['sup_id']}", headers=owner_b_headers)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Test 11: Inactive membership rejection
# ---------------------------------------------------------------------------

def test_11_inactive_membership_rejection(shop_setup):
    s = shop_setup
    db = TestingSessionLocal()
    # Deactivate the cashier
    member = db.query(ShopMember).filter(
        ShopMember.shop_id == s["shop_id"],
        ShopMember.user_id == s["cashier_id"],
    ).first()
    member.is_active = False
    db.commit()
    db.close()

    # Cashier attempts operational action -> 403 Forbidden (inactive)
    res = client.post(
        "/api/v1/sales",
        json={
            "payment_method": "CASH",
            "items": [{"product_id": str(s["prod_id"]), "quantity": 1, "unit_price": 120.0}],
        },
        headers=s["cashier_headers"],
    )
    assert res.status_code in (400, 403)


# ---------------------------------------------------------------------------
# Test 12: Cashier direct price override on verified product forbidden
# ---------------------------------------------------------------------------

def test_12_cashier_direct_price_override_on_verified_product_forbidden(shop_setup):
    s = shop_setup
    ch = s["cashier_headers"]
    mh = s["manager_headers"]
    prod_id = str(s["prod_id"])

    # 1. Cashier attempts to override selling price on VERIFIED product -> 403 Forbidden
    res = client.put(
        f"/api/v1/products/{prod_id}",
        json={"selling_price": 130.0},
        headers=ch,
    )
    assert res.status_code == 403
    assert "Manager or Owner role required" in res.json()["detail"]

    # 2. Cashier attempts to override MRP on VERIFIED product -> 403 Forbidden
    res = client.put(
        f"/api/v1/products/{prod_id}",
        json={"mrp": 150.0},
        headers=ch,
    )
    assert res.status_code == 403
    assert "Manager or Owner role required" in res.json()["detail"]

    # 3. Cashier performs non-pricing update (e.g. category) -> 200 OK
    res = client.put(
        f"/api/v1/products/{prod_id}",
        json={"category": "Grains & Rice"},
        headers=ch,
    )
    assert res.status_code == 200
    assert res.json()["category"] == "Grains & Rice"
    assert res.json()["selling_price"] == 120.0  # Selling price unchanged

    # 4. Manager overrides selling price on VERIFIED product -> 200 OK
    res = client.put(
        f"/api/v1/products/{prod_id}",
        json={"selling_price": 125.0},
        headers=mh,
    )
    assert res.status_code == 200
    assert res.json()["selling_price"] == 125.0
