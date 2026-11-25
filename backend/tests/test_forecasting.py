import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.session import Base
import db.models
from db.models.user import User
from db.models.shop import Shop
from db.models.product import Product
from db.models.sale import Sale
from db.models.sale_item import SaleItem
from schemas.forecast import (
    ForecastTier,
    ConfidenceLevel,
    ForecastStatus,
    ProductDemandForecast,
    ShopForecastSummary,
)
from services.forecasting import (
    forecast_product_demand,
    forecast_shop_demand,
    _calculate_ewma,
)

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def create_shop(db, name="Kirana One") -> Shop:
    user = User(
        id=uuid.uuid4(),
        email=f"owner_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed_pw",
        is_active=True,
    )
    db.add(user)
    db.flush()

    shop = Shop(
        id=uuid.uuid4(),
        shop_name=name,
        owner_name="Owner",
        business_type="Grocery/Kirana",
        owner_id=user.id,
    )
    db.add(shop)
    db.commit()
    db.refresh(shop)
    return shop


def create_product(
    db,
    shop_id: uuid.UUID,
    name: str = "Sugar",
    stock: float = 50.0,
    unit: str = "kg",
    reorder_level: int = 10,
    created_at: datetime = None,
) -> Product:
    prod = Product(
        id=uuid.uuid4(),
        shop_id=shop_id,
        name=name,
        category="Staples",
        selling_price=60.0,
        purchase_price=45.0,
        current_stock=stock,
        reorder_level=reorder_level,
        unit=unit,
        pricing_status="VERIFIED",
        is_active=True,
        created_at=created_at or datetime.now(timezone.utc) - timedelta(days=30),
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod


def add_sale(
    db,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: float,
    unit_price: float = 60.0,
    tx_datetime: datetime = None,
) -> Sale:
    dt = tx_datetime or datetime.now(timezone.utc)
    sale = Sale(
        id=uuid.uuid4(),
        shop_id=shop_id,
        total_amount=quantity * unit_price,
        payment_method="cash",
        created_at=dt,
    )
    db.add(sale)
    db.flush()

    item = SaleItem(
        id=uuid.uuid4(),
        sale_id=sale.id,
        product_id=product_id,
        quantity=quantity,
        unit_price=unit_price,
        created_at=dt,
    )
    db.add(item)
    db.commit()
    return sale


# -----------------------------------------------------------------------------
# Unit Tests for EWMA Arithmetic
# -----------------------------------------------------------------------------

def test_ewma_manual_arithmetic():
    # S_0 = 10.0
    # S_1 = 0.3 * 20.0 + 0.7 * 10.0 = 6.0 + 7.0 = 13.0
    # S_2 = 0.3 * 0.0 + 0.7 * 13.0 = 9.1
    series = [Decimal("10.0"), Decimal("20.0"), Decimal("0.0")]
    result = _calculate_ewma(series, alpha=Decimal("0.3"))
    assert result == Decimal("9.1")


def test_ewma_empty_series():
    assert _calculate_ewma([]) == Decimal("0.0")


# -----------------------------------------------------------------------------
# Tier 3: Cold-Start Tests
# -----------------------------------------------------------------------------

def test_tier_3_cold_start_product(db_session):
    shop = create_shop(db_session)
    prod = create_product(db_session, shop.id, name="Organic Quinoa", stock=25.0)

    forecast = forecast_product_demand(db_session, shop.id, prod.id)

    assert forecast.forecast_tier == ForecastTier.TIER_3_COLD_START
    assert forecast.confidence_level == ConfidenceLevel.NONE
    assert forecast.forecast_status == ForecastStatus.NEW_PRODUCT_NO_SALES_HISTORY
    assert forecast.total_valid_sales == 0
    assert forecast.daily_demand_rate == 0.0
    assert forecast.expected_seven_day_demand == 0.0
    assert forecast.days_to_stockout is None
    assert forecast.recommended_reorder_quantity is None
    assert any("no recorded sales" in a.lower() for a in forecast.assumptions)
    assert any("no sales history" in w.lower() for w in forecast.warnings)


def test_tier_3_cold_start_out_of_stock(db_session):
    shop = create_shop(db_session)
    prod = create_product(db_session, shop.id, name="Zero Stock Item", stock=0.0)

    forecast = forecast_product_demand(db_session, shop.id, prod.id)

    assert forecast.forecast_tier == ForecastTier.TIER_3_COLD_START
    assert forecast.current_stock == 0.0
    assert forecast.days_to_stockout == 0.0
    assert forecast.forecast_status == ForecastStatus.OUT_OF_STOCK
    assert any("currently out of stock" in w.lower() for w in forecast.warnings)


# -----------------------------------------------------------------------------
# Tier 2: Sparse Sales History Tests
# -----------------------------------------------------------------------------

def test_tier_2_sparse_history_linear_run_rate(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Created 10 days ago
    created = now - timedelta(days=9)
    prod = create_product(db_session, shop.id, name="Turmeric Powder", stock=20.0, created_at=created)

    # 2 sales events: Day 1 (4 units), Day 6 (6 units) -> 10 units total over 10 observable days
    add_sale(db_session, shop.id, prod.id, quantity=4.0, tx_datetime=created)
    add_sale(db_session, shop.id, prod.id, quantity=6.0, tx_datetime=created + timedelta(days=5))

    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now)

    assert forecast.forecast_tier == ForecastTier.TIER_2_SPARSE
    assert forecast.confidence_level == ConfidenceLevel.LOW
    assert forecast.total_valid_sales == 2
    assert forecast.observable_days == 10
    # 10 units / 10 days = 1.0 unit/day
    assert forecast.daily_demand_rate == 1.0
    assert forecast.expected_seven_day_demand == 7.0
    # Stock 20.0 / 1.0 = 20.0 days
    assert forecast.days_to_stockout == 20.0
    assert any("sparse" in w.lower() for w in forecast.warnings)


# -----------------------------------------------------------------------------
# Tier 1: Sufficient Sales History & EWMA Tests
# -----------------------------------------------------------------------------

def test_tier_1_sufficient_history_ewma(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Observable window: 16 calendar days
    created = now - timedelta(days=15)
    prod = create_product(db_session, shop.id, name="Refined Sugar", stock=50.0, unit="kg", created_at=created)

    # Add 6 sales events on specific days across the 16-day window
    # Days with sales: Day 0 (2kg), Day 3 (4kg), Day 7 (2kg), Day 10 (3kg), Day 12 (1kg), Day 15 (4kg)
    # Zero-sales days: 10 days
    add_sale(db_session, shop.id, prod.id, 2.0, tx_datetime=created)
    add_sale(db_session, shop.id, prod.id, 4.0, tx_datetime=created + timedelta(days=3))
    add_sale(db_session, shop.id, prod.id, 2.0, tx_datetime=created + timedelta(days=7))
    add_sale(db_session, shop.id, prod.id, 3.0, tx_datetime=created + timedelta(days=10))
    add_sale(db_session, shop.id, prod.id, 1.0, tx_datetime=created + timedelta(days=12))
    add_sale(db_session, shop.id, prod.id, 4.0, tx_datetime=created + timedelta(days=15))

    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now)

    assert forecast.forecast_tier == ForecastTier.TIER_1_SUFFICIENT
    assert forecast.confidence_level == ConfidenceLevel.MEDIUM
    assert forecast.total_valid_sales == 6
    assert forecast.observable_days == 16
    assert forecast.daily_demand_rate > 0.0
    assert forecast.expected_seven_day_demand > 0.0
    assert forecast.days_to_stockout > 0.0
    assert any("ewma" in a.lower() for a in forecast.assumptions)
    assert any("zero-sales days" in a.lower() for a in forecast.assumptions)


def test_tier_1_high_confidence_level(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=24)
    prod = create_product(db_session, shop.id, name="Daily Milk", stock=100.0, unit="packet", created_at=created)

    # 22 sales events over 25 days
    for i in range(22):
        add_sale(db_session, shop.id, prod.id, quantity=5.0, tx_datetime=created + timedelta(days=i))

    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now)

    assert forecast.forecast_tier == ForecastTier.TIER_1_SUFFICIENT
    assert forecast.total_valid_sales == 22
    assert forecast.confidence_level == ConfidenceLevel.HIGH


# -----------------------------------------------------------------------------
# Stockout Prediction & Reorder Recommendation Tests
# -----------------------------------------------------------------------------

def test_stockout_prediction_under_7_days_alert(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    # Stock is only 4 units, demand is ~1 unit/day -> ~4 days left
    prod = create_product(db_session, shop.id, name="Atta 10kg", stock=4.0, created_at=created)
    add_sale(db_session, shop.id, prod.id, quantity=10.0, tx_datetime=created)

    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now)

    assert forecast.days_to_stockout == 4.0
    assert forecast.forecast_status == ForecastStatus.LOW_STOCK
    assert any("stockout risk within 7 days" in w.lower() for w in forecast.warnings)


def test_reorder_recommendation_math(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    # Current stock: 5 units. Reorder level (safety stock): 10 units.
    prod = create_product(db_session, shop.id, name="Sunflower Oil", stock=5.0, reorder_level=10, created_at=created)

    # 10 units sold over 10 days = 1.0 unit/day
    add_sale(db_session, shop.id, prod.id, quantity=10.0, tx_datetime=created)

    # Configurable lead time: 4 days.
    # Target inventory = (1.0 * 4) + 10 = 14 units.
    # Recommended reorder = 14 - 5 = 9.0 units.
    forecast = forecast_product_demand(
        db_session,
        shop.id,
        prod.id,
        as_of_date=now,
        lead_time_days=4,
    )

    assert forecast.daily_demand_rate == 1.0
    assert forecast.recommended_reorder_quantity == 9.0
    assert forecast.is_reorder_provisional is True  # reorder_level used as provisional safety stock


def test_reorder_recommendation_explicit_safety_stock(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    prod = create_product(db_session, shop.id, name="Basmati Rice", stock=20.0, reorder_level=0, created_at=created)
    add_sale(db_session, shop.id, prod.id, quantity=10.0, tx_datetime=created)

    # Daily rate: 1.0. Lead time: 3 days. Safety stock explicitly 15.0. Current stock: 20.0.
    # Target = (1.0 * 3) + 15 = 18.0. Current stock = 20.0.
    # Deficit = 18 - 20 = -2 -> max(0, -2) = 0.0 (no reorder needed)
    forecast = forecast_product_demand(
        db_session,
        shop.id,
        prod.id,
        as_of_date=now,
        lead_time_days=3,
        safety_stock=15.0,
    )

    assert forecast.recommended_reorder_quantity == 0.0
    assert forecast.is_reorder_provisional is False


# -----------------------------------------------------------------------------
# Transaction Filtering Tests (Zero-Price & Invalid Records)
# -----------------------------------------------------------------------------

def test_promotional_zero_price_included_by_default(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    prod = create_product(db_session, shop.id, name="Free Sample Biscuit", stock=50.0, created_at=created)

    # Promotional sale: quantity=5, unit_price=0.0
    add_sale(db_session, shop.id, prod.id, quantity=5.0, unit_price=0.0, tx_datetime=created)

    forecast_included = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now, include_zero_price=True)
    assert forecast_included.total_valid_sales == 1
    assert forecast_included.daily_demand_rate == 0.5
    assert any("zero-price promotional" in a.lower() for a in forecast_included.assumptions)

    forecast_excluded = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now, include_zero_price=False)
    assert forecast_excluded.total_valid_sales == 0
    assert forecast_excluded.forecast_tier == ForecastTier.TIER_3_COLD_START


def test_invalid_negative_or_zero_quantities_ignored(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)
    prod = create_product(db_session, shop.id, name="Invalid Tx Product", stock=10.0, created_at=created)

    # Directly inject invalid item with quantity=0 or negative
    sale = Sale(id=uuid.uuid4(), shop_id=shop.id, total_amount=0.0, payment_method="cash", created_at=created)
    db_session.add(sale)
    db_session.flush()
    item_invalid = SaleItem(id=uuid.uuid4(), sale_id=sale.id, product_id=prod.id, quantity=0, unit_price=10.0, created_at=created)
    db_session.add(item_invalid)
    db_session.commit()

    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now)
    assert forecast.total_valid_sales == 0
    assert forecast.forecast_tier == ForecastTier.TIER_3_COLD_START


# -----------------------------------------------------------------------------
# Tenant Isolation Tests
# -----------------------------------------------------------------------------

def test_tenant_isolation_multiple_shops(db_session):
    shop_a = create_shop(db_session, name="Shop Alpha")
    shop_b = create_shop(db_session, name="Shop Beta")

    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=9)

    prod_a = create_product(db_session, shop_a.id, name="Sugar Shop A", stock=50.0, created_at=created)
    prod_b = create_product(db_session, shop_b.id, name="Sugar Shop B", stock=50.0, created_at=created)

    # Record 10 sales for Shop A
    for i in range(10):
        add_sale(db_session, shop_a.id, prod_a.id, quantity=2.0, tx_datetime=created + timedelta(days=i))

    # Forecast for Shop B product must have ZERO sales (pure cold start)
    forecast_b = forecast_product_demand(db_session, shop_b.id, prod_b.id, as_of_date=now)
    assert forecast_b.total_valid_sales == 0
    assert forecast_b.forecast_tier == ForecastTier.TIER_3_COLD_START

    # Cross-tenant query must raise ValueError
    with pytest.raises(ValueError, match="not found in shop"):
        forecast_product_demand(db_session, shop_b.id, prod_a.id)


# -----------------------------------------------------------------------------
# Shop-Wide Forecast Summary Test
# -----------------------------------------------------------------------------

def test_forecast_shop_demand_summary(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=15)

    # 1 Tier 1 product (6 sales over 16 days)
    prod1 = create_product(db_session, shop.id, name="Prod 1 - Tier 1", stock=20.0, created_at=created)
    for i in range(6):
        add_sale(db_session, shop.id, prod1.id, quantity=2.0, tx_datetime=created + timedelta(days=i * 2))

    # 1 Tier 2 product (2 sales over 16 days)
    prod2 = create_product(db_session, shop.id, name="Prod 2 - Tier 2", stock=3.0, created_at=created)
    add_sale(db_session, shop.id, prod2.id, quantity=1.0, tx_datetime=created)
    add_sale(db_session, shop.id, prod2.id, quantity=1.0, tx_datetime=created + timedelta(days=5))

    # 1 Tier 3 product (0 sales, 0 stock)
    prod3 = create_product(db_session, shop.id, name="Prod 3 - Tier 3", stock=0.0, created_at=created)

    summary: ShopForecastSummary = forecast_shop_demand(db_session, shop.id, as_of_date=now)

    assert summary.total_products_analyzed == 3
    assert summary.tier_1_count == 1
    assert summary.tier_2_count == 1
    assert summary.tier_3_count == 1
    assert summary.out_of_stock_count == 1  # prod3 is stock=0
    assert len(summary.forecasts) == 3


def test_zero_demand_positive_stock_has_none_stockout(db_session):
    shop = create_shop(db_session)
    now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
    # Observable days: 10 days
    created = now - timedelta(days=9)
    prod = create_product(db_session, shop.id, name="Zero Velocity Item", stock=15.0, created_at=created)

    # No sales events
    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now)

    assert forecast.current_stock == 15.0
    assert forecast.daily_demand_rate == 0.0
    assert forecast.days_to_stockout is None


def test_missing_timestamp_fallback_safe(db_session):
    shop = create_shop(db_session)
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=5)
    prod = create_product(db_session, shop.id, name="Null Timestamp Item", stock=10.0, created_at=created)

    # Sale created with default timestamp
    sale = Sale(id=uuid.uuid4(), shop_id=shop.id, total_amount=60.0, payment_method="cash")
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(id=uuid.uuid4(), sale_id=sale.id, product_id=prod.id, quantity=2.0, unit_price=30.0)
    db_session.add(item)
    db_session.commit()

    forecast = forecast_product_demand(db_session, shop.id, prod.id, as_of_date=now + timedelta(hours=1))
    assert forecast.total_valid_sales == 1
    assert forecast.daily_demand_rate > 0.0

