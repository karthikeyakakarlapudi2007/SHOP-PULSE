"""
Stage 7.2: Demand Forecasting API & Role-Based Access Control Test Suite.

Verifies:
1. Unauthenticated requests are rejected (401 Unauthorized).
2. Cashier role is rejected with 403 Forbidden.
3. Owner and Manager roles are permitted (200 OK).
4. Cross-tenant product access is rejected (404 Not Found, zero data leakage).
5. Shop-level forecast accuracy, catalog counts, and tenant isolation.
6. Filtering by product_id, forecast_tier, forecast_status, and confidence_level.
7. Empty product catalog handling.
8. Cold-start (Tier 3) products with zero sales.
9. Out-of-stock products with zero stock.
10. Sparse sales history (Tier 2).
11. Sufficient sales history (Tier 1 EWMA).
12. Validation of query parameters (invalid UUID, enum, alpha, lead_time -> 422).
13. Decimal serialization (all numeric fields serialized as JSON floats/numbers).
14. Cache hit on repeated calls and cross-tenant cache isolation.
15. Cache invalidation on sale checkout.
16. Cache invalidation on purchase creation.
17. Cache bypass via no_cache=true.
"""

from datetime import datetime, timezone, timedelta
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
from db.models.sale import Sale
from db.models.sale_item import SaleItem
from api.deps import get_db
from services.forecasting import get_forecast_cache, invalidate_forecast_cache

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
    invalidate_forecast_cache()
    yield
    invalidate_forecast_cache()
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


@pytest.fixture
def auth_setup():
    """
    Sets up two shops (Shop Alpha and Shop Beta) with Owner, Manager, and Cashier for Shop Alpha.
    """
    # 1. Shop Alpha Owner
    alpha_owner_id, alpha_owner_headers = create_user_and_token("alpha_owner@example.com")
    shop_alpha_id = create_shop_for_user(alpha_owner_headers, "Shop Alpha")

    # 2. Shop Alpha Manager
    alpha_manager_id, alpha_manager_headers = create_user_and_token("alpha_manager@example.com")
    res_mgr = client.post(
        f"/api/v1/shops/{shop_alpha_id}/members",
        json={"user_id": str(alpha_manager_id), "role": "MANAGER"},
        headers=alpha_owner_headers,
    )
    assert res_mgr.status_code == 201

    # 3. Shop Alpha Cashier
    alpha_cashier_id, alpha_cashier_headers = create_user_and_token("alpha_cashier@example.com")
    res_csh = client.post(
        f"/api/v1/shops/{shop_alpha_id}/members",
        json={"user_id": str(alpha_cashier_id), "role": "CASHIER"},
        headers=alpha_owner_headers,
    )
    assert res_csh.status_code == 201

    # 4. Shop Beta Owner (Tenant Isolation test)
    beta_owner_id, beta_owner_headers = create_user_and_token("beta_owner@example.com")
    shop_beta_id = create_shop_for_user(beta_owner_headers, "Shop Beta")

    # 5. Populate products in Shop Alpha
    db = TestingSessionLocal()

    # Product 1: Rice (Tier 1 history)
    prod_rice = Product(
        id=uuid.uuid4(),
        shop_id=shop_alpha_id,
        name="Basmati Rice 1kg",
        selling_price=120.0,
        purchase_price=90.0,
        mrp=140.0,
        unit="kg",
        price_basis_quantity=1.0,
        price_basis_unit="kg",
        current_stock=50.0,
        reorder_level=10,
        pricing_status="VERIFIED",
        is_active=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=20),
    )

    # Product 2: Sugar (Sparse / Tier 2)
    prod_sugar = Product(
        id=uuid.uuid4(),
        shop_id=shop_alpha_id,
        name="Refined Sugar 1kg",
        selling_price=45.0,
        purchase_price=38.0,
        mrp=50.0,
        unit="kg",
        price_basis_quantity=1.0,
        price_basis_unit="kg",
        current_stock=15.0,
        reorder_level=5,
        pricing_status="VERIFIED",
        is_active=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=6),
    )

    # Product 3: Milk (Cold Start / Tier 3, Zero stock)
    prod_milk = Product(
        id=uuid.uuid4(),
        shop_id=shop_alpha_id,
        name="Toned Milk 500ml",
        selling_price=30.0,
        purchase_price=26.0,
        mrp=32.0,
        unit="packet",
        price_basis_quantity=1.0,
        price_basis_unit="packet",
        current_stock=0.0,
        reorder_level=5,
        pricing_status="VERIFIED",
        is_active=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )

    # Product in Shop Beta (for cross-tenant checks)
    prod_beta = Product(
        id=uuid.uuid4(),
        shop_id=shop_beta_id,
        name="Beta Tea Powder",
        selling_price=80.0,
        purchase_price=65.0,
        mrp=95.0,
        unit="packet",
        price_basis_quantity=1.0,
        price_basis_unit="packet",
        current_stock=25.0,
        reorder_level=5,
        pricing_status="VERIFIED",
        is_active=True,
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )

    db.add_all([prod_rice, prod_sugar, prod_milk, prod_beta])
    db.commit()

    # Create 6 sales events for Rice spread over 18 days (Tier 1)
    base_time = datetime.now(timezone.utc) - timedelta(days=18)
    for i in range(6):
        sale = Sale(
            id=uuid.uuid4(),
            shop_id=shop_alpha_id,
            total_amount=240.0,
            payment_method="cash",
            created_at=base_time + timedelta(days=i * 3),
        )
        db.add(sale)
        db.flush()
        db.add(SaleItem(
            id=uuid.uuid4(),
            sale_id=sale.id,
            product_id=prod_rice.id,
            quantity=2.0,
            unit_price=120.0,
        ))

    # Create 2 sales events for Sugar (Tier 2)
    for i in range(2):
        sale = Sale(
            id=uuid.uuid4(),
            shop_id=shop_alpha_id,
            total_amount=45.0,
            payment_method="cash",
            created_at=datetime.now(timezone.utc) - timedelta(days=i + 1),
        )
        db.add(sale)
        db.flush()
        db.add(SaleItem(
            id=uuid.uuid4(),
            sale_id=sale.id,
            product_id=prod_sugar.id,
            quantity=1.0,
            unit_price=45.0,
        ))

    db.commit()
    prod_rice_id = prod_rice.id
    prod_sugar_id = prod_sugar.id
    prod_milk_id = prod_milk.id
    prod_beta_id = prod_beta.id
    db.close()

    return {
        "shop_alpha_id": shop_alpha_id,
        "alpha_owner_headers": alpha_owner_headers,
        "alpha_manager_headers": alpha_manager_headers,
        "alpha_cashier_headers": alpha_cashier_headers,
        "shop_beta_id": shop_beta_id,
        "beta_owner_headers": beta_owner_headers,
        "prod_rice_id": prod_rice_id,
        "prod_sugar_id": prod_sugar_id,
        "prod_milk_id": prod_milk_id,
        "prod_beta_id": prod_beta_id,
    }


# -----------------------------------------------------------------------------
# 1. Authentication & RBAC Tests
# -----------------------------------------------------------------------------

def test_demand_forecast_unauthenticated():
    """Unauthenticated requests must receive HTTP 401 Unauthorized."""
    res = client.get("/api/v1/insights/demand-forecast")
    assert res.status_code == 401
    assert "detail" in res.json()


def test_demand_forecast_cashier_forbidden(auth_setup):
    """CASHIER role must receive HTTP 403 Forbidden."""
    headers = auth_setup["alpha_cashier_headers"]
    res = client.get("/api/v1/insights/demand-forecast", headers=headers)
    assert res.status_code == 403
    assert "Operation requires elevated role" in res.json()["detail"]
    assert "cashier" in res.json()["detail"].lower()


def test_demand_forecast_owner_permitted(auth_setup):
    """OWNER role must receive HTTP 200 with complete shop summary."""
    headers = auth_setup["alpha_owner_headers"]
    res = client.get("/api/v1/insights/demand-forecast", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["shop_id"] == str(auth_setup["shop_alpha_id"])
    assert data["total_products_analyzed"] == 3
    assert len(data["forecasts"]) == 3


def test_demand_forecast_manager_permitted(auth_setup):
    """MANAGER role must receive HTTP 200 with complete shop summary."""
    headers = auth_setup["alpha_manager_headers"]
    res = client.get("/api/v1/insights/demand-forecast", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["shop_id"] == str(auth_setup["shop_alpha_id"])
    assert data["total_products_analyzed"] == 3


# -----------------------------------------------------------------------------
# 2. Cross-Tenant Data Isolation Tests
# -----------------------------------------------------------------------------

def test_cross_tenant_product_access_rejected(auth_setup):
    """
    Shop Alpha owner attempting to query product from Shop Beta must receive 404.
    Zero information leakage about the product's existence in another shop.
    """
    alpha_headers = auth_setup["alpha_owner_headers"]
    beta_prod_id = auth_setup["prod_beta_id"]

    res = client.get(
        f"/api/v1/insights/demand-forecast?product_id={beta_prod_id}",
        headers=alpha_headers,
    )
    assert res.status_code == 404
    assert f"Product '{beta_prod_id}' not found." in res.json()["detail"]


def test_shop_forecast_accuracy_and_isolation(auth_setup):
    """
    Shop Beta has 1 product with 0 sales.
    Shop Alpha has 3 products with active sales.
    Verify that Shop Beta only sees its own product and zero sales from Alpha.
    """
    beta_headers = auth_setup["beta_owner_headers"]
    res = client.get("/api/v1/insights/demand-forecast", headers=beta_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["shop_id"] == str(auth_setup["shop_beta_id"])
    assert data["total_products_analyzed"] == 1
    assert data["tier_3_count"] == 1
    assert len(data["forecasts"]) == 1
    assert data["forecasts"][0]["product_id"] == str(auth_setup["prod_beta_id"])
    assert data["forecasts"][0]["total_valid_sales"] == 0
    assert data["forecasts"][0]["daily_demand_rate"] == 0.0


# -----------------------------------------------------------------------------
# 3. Filtering Tests (Product ID, Tier, Status, Confidence)
# -----------------------------------------------------------------------------

def test_filter_by_product_id(auth_setup):
    """Filtering by product_id returns forecast for that specific product."""
    headers = auth_setup["alpha_owner_headers"]
    prod_id = auth_setup["prod_rice_id"]

    res = client.get(
        f"/api/v1/insights/demand-forecast?product_id={prod_id}",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_products_analyzed"] == 1
    assert len(data["forecasts"]) == 1
    assert data["forecasts"][0]["product_id"] == str(prod_id)
    assert data["forecasts"][0]["product_name"] == "Basmati Rice 1kg"
    assert data["forecasts"][0]["forecast_tier"] == "TIER_1_SUFFICIENT"


def test_filter_by_forecast_tier(auth_setup):
    """Filtering by forecast_tier returns only matching forecasts."""
    headers = auth_setup["alpha_owner_headers"]

    # Filter for Tier 1
    res = client.get(
        "/api/v1/insights/demand-forecast?forecast_tier=TIER_1_SUFFICIENT",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_products_analyzed"] == 3  # Shop total analyzed
    assert len(data["forecasts"]) == 1
    assert data["forecasts"][0]["forecast_tier"] == "TIER_1_SUFFICIENT"
    assert data["forecasts"][0]["product_id"] == str(auth_setup["prod_rice_id"])

    # Filter for Tier 3
    res3 = client.get(
        "/api/v1/insights/demand-forecast?forecast_tier=TIER_3_COLD_START",
        headers=headers,
    )
    assert res3.status_code == 200
    data3 = res3.json()
    assert len(data3["forecasts"]) == 1
    assert data3["forecasts"][0]["forecast_tier"] == "TIER_3_COLD_START"
    assert data3["forecasts"][0]["product_id"] == str(auth_setup["prod_milk_id"])


def test_filter_by_confidence_level(auth_setup):
    """Filtering by confidence_level returns only matching forecasts."""
    headers = auth_setup["alpha_owner_headers"]
    res = client.get(
        "/api/v1/insights/demand-forecast?confidence_level=LOW",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["forecasts"]) == 1
    assert data["forecasts"][0]["confidence_level"] == "LOW"
    assert data["forecasts"][0]["product_id"] == str(auth_setup["prod_sugar_id"])


def test_filter_by_forecast_status(auth_setup):
    """Filtering by forecast_status returns only matching forecasts."""
    headers = auth_setup["alpha_owner_headers"]
    res = client.get(
        "/api/v1/insights/demand-forecast?forecast_status=OUT_OF_STOCK",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["forecasts"]) == 1
    assert data["forecasts"][0]["forecast_status"] == "OUT_OF_STOCK"
    assert data["forecasts"][0]["product_id"] == str(auth_setup["prod_milk_id"])


# -----------------------------------------------------------------------------
# 4. Product Catalog States (Empty, Cold Start, Out of Stock, Sparse)
# -----------------------------------------------------------------------------

def test_empty_product_catalog():
    """Shop with no products returns empty summary without error."""
    _, headers = create_user_and_token("empty_shop_owner@example.com")
    create_shop_for_user(headers, "Empty Catalog Shop")

    res = client.get("/api/v1/insights/demand-forecast", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_products_analyzed"] == 0
    assert data["tier_1_count"] == 0
    assert data["tier_2_count"] == 0
    assert data["tier_3_count"] == 0
    assert data["out_of_stock_count"] == 0
    assert data["at_risk_stockout_7d_count"] == 0
    assert data["forecasts"] == []


def test_cold_start_and_zero_stock_attributes(auth_setup):
    """Verify milk (0 stock, 0 sales) has precise cold start attributes."""
    headers = auth_setup["alpha_owner_headers"]
    milk_id = auth_setup["prod_milk_id"]

    res = client.get(
        f"/api/v1/insights/demand-forecast?product_id={milk_id}",
        headers=headers,
    )
    assert res.status_code == 200
    fc = res.json()["forecasts"][0]
    assert fc["current_stock"] == 0.0
    assert fc["daily_demand_rate"] == 0.0
    assert fc["expected_seven_day_demand"] == 0.0
    assert fc["days_to_stockout"] == 0.0
    assert fc["confidence_level"] == "NONE"
    assert fc["forecast_tier"] == "TIER_3_COLD_START"
    assert fc["forecast_status"] == "OUT_OF_STOCK"
    assert any("out of stock" in w.lower() for w in fc["warnings"])


# -----------------------------------------------------------------------------
# 5. Parameter Validation Tests
# -----------------------------------------------------------------------------

def test_invalid_query_parameters(auth_setup):
    """Verify FastAPI query validation rejects malformed query params with 422."""
    headers = auth_setup["alpha_owner_headers"]

    # Invalid UUID
    res = client.get("/api/v1/insights/demand-forecast?product_id=not-a-valid-uuid", headers=headers)
    assert res.status_code == 422

    # Invalid Tier Enum
    res = client.get("/api/v1/insights/demand-forecast?forecast_tier=TIER_UNKNOWN", headers=headers)
    assert res.status_code == 422

    # Invalid Alpha (> 1.0)
    res = client.get("/api/v1/insights/demand-forecast?alpha=1.5", headers=headers)
    assert res.status_code == 422

    # Invalid Lead Time (< 1)
    res = client.get("/api/v1/insights/demand-forecast?lead_time_days=0", headers=headers)
    assert res.status_code == 422


def test_decimal_serialization(auth_setup):
    """Ensure all numeric fields are serializable floats/numbers in JSON response."""
    headers = auth_setup["alpha_owner_headers"]
    res = client.get("/api/v1/insights/demand-forecast", headers=headers)
    assert res.status_code == 200
    for fc in res.json()["forecasts"]:
        assert isinstance(fc["current_stock"], (int, float))
        assert isinstance(fc["total_valid_sales"], int)
        assert isinstance(fc["observable_days"], int)
        if fc["daily_demand_rate"] is not None:
            assert isinstance(fc["daily_demand_rate"], (int, float))
        if fc["expected_seven_day_demand"] is not None:
            assert isinstance(fc["expected_seven_day_demand"], (int, float))
        if fc["days_to_stockout"] is not None:
            assert isinstance(fc["days_to_stockout"], (int, float))
        if fc["recommended_reorder_quantity"] is not None:
            assert isinstance(fc["recommended_reorder_quantity"], (int, float))


# -----------------------------------------------------------------------------
# 6. Performance, Caching & Invalidation Tests
# -----------------------------------------------------------------------------

def test_cache_hit_and_shop_isolation(auth_setup):
    """
    Verify caching:
    - First request populates cache.
    - Second request hits cache.
    - Shop Alpha and Shop Beta have isolated caches.
    """
    alpha_headers = auth_setup["alpha_owner_headers"]
    beta_headers = auth_setup["beta_owner_headers"]

    cache = get_forecast_cache()
    cache.clear()
    assert cache.size() == 0

    # 1. Shop Alpha request -> cache miss, then set
    res1 = client.get("/api/v1/insights/demand-forecast", headers=alpha_headers)
    assert res1.status_code == 200
    assert cache.size() == 1

    # 2. Repeated Shop Alpha request -> cache hit
    res2 = client.get("/api/v1/insights/demand-forecast", headers=alpha_headers)
    assert res2.status_code == 200
    assert res2.json() == res1.json()
    assert cache.size() == 1

    # 3. Shop Beta request -> separate tenant cache entry
    res3 = client.get("/api/v1/insights/demand-forecast", headers=beta_headers)
    assert res3.status_code == 200
    assert cache.size() == 2

    # 4. Invalidate Shop Alpha -> only Alpha evicted, Beta remains
    invalidated_count = invalidate_forecast_cache(auth_setup["shop_alpha_id"])
    assert invalidated_count >= 1
    assert cache.size() == 1  # Shop Beta still in cache


def test_cache_invalidation_on_sale_checkout(auth_setup):
    """
    A successful checkout via POST /api/v1/sales must invalidate the shop's forecast cache,
    ensuring subsequent forecast calls immediately reflect the deducted inventory.
    """
    headers = auth_setup["alpha_owner_headers"]
    rice_id = auth_setup["prod_rice_id"]

    # 1. Populate cache
    res1 = client.get(f"/api/v1/insights/demand-forecast?product_id={rice_id}", headers=headers)
    assert res1.status_code == 200
    initial_stock = res1.json()["forecasts"][0]["current_stock"]
    assert initial_stock == 50.0

    # 2. Make a sale of 5 kg of rice via POS
    sale_res = client.post(
        "/api/v1/sales",
        headers=headers,
        json={
            "items": [{"product_id": str(rice_id), "quantity": 5.0, "unit": "kg"}],
            "payment_method": "cash",
        },
    )
    assert sale_res.status_code == 201

    # 3. Next demand-forecast call must return updated stock (45.0) immediately
    res2 = client.get(f"/api/v1/insights/demand-forecast?product_id={rice_id}", headers=headers)
    assert res2.status_code == 200
    new_stock = res2.json()["forecasts"][0]["current_stock"]
    assert new_stock == 45.0


def test_cache_invalidation_on_purchase(auth_setup):
    """
    A successful purchase logged via POST /api/v1/purchases must invalidate the shop's forecast cache,
    ensuring subsequent forecast calls immediately reflect the replenished inventory.
    """
    headers = auth_setup["alpha_owner_headers"]
    sugar_id = auth_setup["prod_sugar_id"]
    shop_id = auth_setup["shop_alpha_id"]

    # Create a supplier for the purchase
    db = TestingSessionLocal()
    sup = Supplier(
        id=uuid.uuid4(),
        shop_id=shop_id,
        supplier_name="Sugar Wholesale Co",
        phone="9988776655",
    )
    db.add(sup)
    db.commit()
    sup_id = sup.id
    db.close()

    # 1. Populate cache
    res1 = client.get(f"/api/v1/insights/demand-forecast?product_id={sugar_id}", headers=headers)
    assert res1.status_code == 200
    initial_stock = res1.json()["forecasts"][0]["current_stock"]
    assert initial_stock == 15.0

    # 2. Log a purchase of 20 kg of sugar
    purch_res = client.post(
        "/api/v1/purchases",
        headers=headers,
        json={
            "supplier_id": str(sup_id),
            "items": [
                {
                    "product_id": str(sugar_id),
                    "quantity": 20.0,
                    "unit": "kg",
                    "purchase_price": 38.0,
                }
            ],
        },
    )
    assert purch_res.status_code == 201

    # 3. Next demand-forecast call must show updated stock (35.0)
    res2 = client.get(f"/api/v1/insights/demand-forecast?product_id={sugar_id}", headers=headers)
    assert res2.status_code == 200
    new_stock = res2.json()["forecasts"][0]["current_stock"]
    assert new_stock == 35.0


def test_no_cache_query_parameter(auth_setup):
    """no_cache=true forces database evaluation without reading from cache."""
    headers = auth_setup["alpha_owner_headers"]

    # Request with no_cache=true
    res = client.get("/api/v1/insights/demand-forecast?no_cache=true", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_products_analyzed"] == 3
