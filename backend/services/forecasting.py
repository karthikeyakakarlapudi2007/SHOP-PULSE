import threading
import time
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

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
from services.stock import quantity_number
from services.unit_registry import convert_quantity, try_normalize_unit, UnitError


def _calculate_ewma(series: List[Decimal], alpha: Decimal = Decimal("0.3")) -> Decimal:
    """
    Calculates Exponentially Weighted Moving Average (EWMA) over a chronological series.
    Initial EWMA value S_0 = series[0].
    S_t = alpha * series[t] + (1 - alpha) * S_{t-1}
    """
    if not series:
        return Decimal("0.0")
    s = series[0]
    one_minus_alpha = Decimal("1.0") - alpha
    for val in series[1:]:
        s = (alpha * val) + (one_minus_alpha * s)
    return s


def forecast_product_demand(
    db: Session,
    shop_id: UUID,
    product_id: UUID,
    as_of_date: Optional[datetime] = None,
    lead_time_days: int = 3,
    safety_stock: Optional[float] = None,
    alpha: float = 0.3,
    include_zero_price: bool = True,
) -> ProductDemandForecast:
    """
    Generates a deterministic 3-tier demand forecast and stockout prediction for a single product.
    Enforces tenant isolation, unit normalization, calendar-day continuity, and Decimal precision.
    """
    # 1. Fetch and validate product within shop tenancy
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.shop_id == shop_id)
        .first()
    )
    if not product:
        raise ValueError(f"Product {product_id} not found in shop {shop_id}.")

    # Current stock and normalized unit
    current_stock_val = quantity_number(product.current_stock if product.current_stock is not None else 0)
    norm_unit = try_normalize_unit(product.unit) or str(product.unit or "pcs")

    now_dt = as_of_date or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    now_date = now_dt.date()

    assumptions: List[str] = []
    warnings: List[str] = []
    is_provisional = False

    # 2. Query valid historical sale items for this product
    # Enforces shop tenancy on both product and sale headers
    sale_item_rows = (
        db.query(
            SaleItem.id,
            SaleItem.quantity,
            SaleItem.unit_price,
            Sale.created_at,
            Sale.total_amount,
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            SaleItem.product_id == product.id,
            Sale.shop_id == shop_id,
            SaleItem.quantity > 0,
        )
        .order_by(Sale.created_at.asc())
        .all()
    )

    # 3. Filter and normalize transactions
    valid_sales_events: List[Dict[str, Any]] = []
    has_zero_price_items = False
    unit_conversion_failed = False

    for item_id, qty, unit_price, sale_created_at, sale_total in sale_item_rows:
        # Investigate zero-price items (promotional vs test)
        if unit_price <= 0 or (sale_total is not None and sale_total <= 0):
            has_zero_price_items = True
            if not include_zero_price:
                continue

        # Safely determine transaction timestamp
        tx_dt = sale_created_at
        if tx_dt is None:
            tx_dt = product.created_at or now_dt
        if tx_dt.tzinfo is None:
            tx_dt = tx_dt.replace(tzinfo=timezone.utc)

        # Ignore future transactions relative to as_of_date
        if tx_dt.date() > now_date:
            continue

        # Quantity is stored in product's inventory unit in SaleItem
        # If any caller has alternative requested units, normalize via unit registry
        qty_dec = Decimal(str(qty))

        valid_sales_events.append({
            "item_id": item_id,
            "quantity": qty_dec,
            "date": tx_dt.date(),
            "datetime": tx_dt,
            "unit_price": unit_price,
        })

    if has_zero_price_items and include_zero_price:
        assumptions.append("Includes zero-price promotional items representing physical inventory depletion.")

    total_valid_sales = len(valid_sales_events)

    # Determine observable calendar window
    if product.created_at:
        p_created = product.created_at
        if p_created.tzinfo is None:
            p_created = p_created.replace(tzinfo=timezone.utc)
        p_created_date = p_created.date()
    else:
        p_created_date = now_date

    if valid_sales_events:
        earliest_sale_date = valid_sales_events[0]["date"]
        start_date = min(earliest_sale_date, p_created_date)
    else:
        start_date = p_created_date

    if now_date < start_date:
        start_date = now_date

    observable_days = max((now_date - start_date).days + 1, 1)

    # -------------------------------------------------------------------------
    # 4. Three-Tier Forecasting Evaluation
    # -------------------------------------------------------------------------

    # TIER 3: Cold-Start (0 valid sales events)
    if total_valid_sales == 0:
        forecast_tier = ForecastTier.TIER_3_COLD_START
        confidence_level = ConfidenceLevel.NONE
        forecast_status = ForecastStatus.NEW_PRODUCT_NO_SALES_HISTORY
        daily_demand_rate = 0.0
        expected_seven_day_demand = 0.0
        days_to_stockout = 0.0 if current_stock_val <= 0 else None
        recommended_reorder_qty = None
        assumptions.append("Product has no recorded sales transactions. Category demand is never fabricated.")
        warnings.append("No sales history recorded for this product.")
        if current_stock_val <= 0:
            forecast_status = ForecastStatus.OUT_OF_STOCK
            warnings.append("Product is currently out of stock.")

        return ProductDemandForecast(
            product_id=product.id,
            product_name=product.name,
            current_stock=float(current_stock_val),
            normalized_unit=norm_unit,
            total_valid_sales=0,
            observable_days=observable_days,
            daily_demand_rate=daily_demand_rate,
            expected_seven_day_demand=expected_seven_day_demand,
            days_to_stockout=days_to_stockout,
            recommended_reorder_quantity=recommended_reorder_qty,
            confidence_level=confidence_level,
            forecast_tier=forecast_tier,
            forecast_status=forecast_status,
            is_reorder_provisional=True,
            assumptions=assumptions,
            warnings=warnings,
        )

    # TIER 1: Sufficient Sales History (>= 5 events AND >= 14 observable calendar days)
    if total_valid_sales >= 5 and observable_days >= 14:
        forecast_tier = ForecastTier.TIER_1_SUFFICIENT
        confidence_level = ConfidenceLevel.HIGH if total_valid_sales >= 20 else ConfidenceLevel.MEDIUM

        # Build chronological calendar-day series explicitly including zero-sales days
        daily_quantities: Dict[date, Decimal] = {}
        for d_offset in range(observable_days):
            day_cursor = start_date + timedelta(days=d_offset)
            daily_quantities[day_cursor] = Decimal("0.0")

        for event in valid_sales_events:
            event_d = event["date"]
            if event_d in daily_quantities:
                daily_quantities[event_d] += event["quantity"]

        # Chronological series
        series_points = [daily_quantities[start_date + timedelta(days=i)] for i in range(observable_days)]
        zero_days_count = sum(1 for p in series_points if p == Decimal("0.0"))

        # Exponentially Weighted Moving Average (alpha = 0.3)
        alpha_dec = Decimal(str(alpha))
        ewma_rate_dec = _calculate_ewma(series_points, alpha=alpha_dec)
        if ewma_rate_dec < Decimal("0.0"):
            ewma_rate_dec = Decimal("0.0")

        daily_demand_rate = float(round(ewma_rate_dec, 4))
        expected_seven_day_demand = float(round(ewma_rate_dec * Decimal("7.0"), 3))

        assumptions.append(
            f"Calculated using calendar-day EWMA (alpha={alpha}) over {observable_days} observable days "
            f"({len(series_points)} continuous points, including {zero_days_count} zero-sales days)."
        )
        if zero_days_count / len(series_points) > 0.6:
            warnings.append(
                f"Intermittent demand pattern: {zero_days_count} of {len(series_points)} days "
                f"({round(zero_days_count / len(series_points) * 100, 1)}%) had zero sales."
            )

    # TIER 2: Sparse Sales History (1-4 events OR < 14 observable days)
    else:
        forecast_tier = ForecastTier.TIER_2_SPARSE
        confidence_level = ConfidenceLevel.LOW
        total_qty_sold = sum(e["quantity"] for e in valid_sales_events)
        linear_rate_dec = total_qty_sold / Decimal(str(max(observable_days, 1)))
        if linear_rate_dec < Decimal("0.0"):
            linear_rate_dec = Decimal("0.0")

        daily_demand_rate = float(round(linear_rate_dec, 4))
        expected_seven_day_demand = float(round(linear_rate_dec * Decimal("7.0"), 3))

        assumptions.append(
            f"Initial estimate based on limited sales history ({total_valid_sales} sales events over "
            f"{observable_days} calendar days). Conservative linear run-rate applied."
        )
        warnings.append("Sparse sales history. Forecast has high uncertainty and is advisory only.")

    # -------------------------------------------------------------------------
    # 5. Stockout Prediction (Days to Stockout)
    # -------------------------------------------------------------------------
    stock_dec = Decimal(str(current_stock_val))
    rate_dec = Decimal(str(daily_demand_rate))

    if stock_dec <= Decimal("0.0"):
        days_to_stockout = 0.0
        forecast_status = ForecastStatus.OUT_OF_STOCK
        warnings.append("Product is currently out of stock.")
    elif rate_dec > Decimal("0.0"):
        raw_days = stock_dec / rate_dec
        days_to_stockout = float(round(raw_days, 1))
        if days_to_stockout <= 7.0:
            forecast_status = ForecastStatus.LOW_STOCK
            warnings.append(f"Stockout risk within 7 days ({days_to_stockout} days remaining).")
        elif product.reorder_level is not None and stock_dec <= Decimal(str(product.reorder_level)):
            forecast_status = ForecastStatus.LOW_STOCK
        else:
            forecast_status = ForecastStatus.ACTIVE if forecast_tier == ForecastTier.TIER_1_SUFFICIENT else ForecastStatus.SPARSE_HISTORY
    else:
        days_to_stockout = None
        forecast_status = ForecastStatus.ACTIVE if forecast_tier == ForecastTier.TIER_1_SUFFICIENT else ForecastStatus.SPARSE_HISTORY
        assumptions.append("No active demand depletion detected (daily demand rate is 0.0).")

    # -------------------------------------------------------------------------
    # 6. Reorder Recommendation
    # -------------------------------------------------------------------------
    # Lead time is configurable, default 3 days
    eff_lead_time = max(lead_time_days, 1)

    if safety_stock is not None:
        eff_safety_stock = Decimal(str(max(safety_stock, 0.0)))
        assumptions.append(f"Safety stock explicitly configured as {safety_stock} {norm_unit}.")
    elif product.reorder_level is not None and product.reorder_level > 0:
        eff_safety_stock = Decimal(str(product.reorder_level))
        is_provisional = True
        assumptions.append(f"Safety stock provisionally derived from configured reorder_level ({product.reorder_level} {norm_unit}).")
    else:
        eff_safety_stock = Decimal("0.0")
        is_provisional = True
        warnings.append("No safety stock configured; reorder recommendation is provisional.")

    if rate_dec > Decimal("0.0"):
        lead_time_demand = rate_dec * Decimal(str(eff_lead_time))
        target_inventory = lead_time_demand + eff_safety_stock
        deficit = target_inventory - max(Decimal("0.0"), stock_dec)
        reorder_qty_dec = max(Decimal("0.0"), deficit)
        recommended_reorder_qty = float(round(reorder_qty_dec, 2))
    elif stock_dec <= Decimal("0.0") and eff_safety_stock > Decimal("0.0"):
        # Zero demand but completely out of stock and safety stock exists
        recommended_reorder_qty = float(round(eff_safety_stock, 2))
    else:
        recommended_reorder_qty = 0.0

    return ProductDemandForecast(
        product_id=product.id,
        product_name=product.name,
        current_stock=float(current_stock_val),
        normalized_unit=norm_unit,
        total_valid_sales=total_valid_sales,
        observable_days=observable_days,
        daily_demand_rate=daily_demand_rate,
        expected_seven_day_demand=expected_seven_day_demand,
        days_to_stockout=days_to_stockout,
        recommended_reorder_quantity=recommended_reorder_qty,
        confidence_level=confidence_level,
        forecast_tier=forecast_tier,
        forecast_status=forecast_status,
        is_reorder_provisional=is_provisional,
        assumptions=assumptions,
        warnings=warnings,
    )


def forecast_shop_demand(
    db: Session,
    shop_id: UUID,
    as_of_date: Optional[datetime] = None,
    lead_time_days: int = 3,
    safety_stock: Optional[float] = None,
    alpha: float = 0.3,
    include_zero_price: bool = True,
) -> ShopForecastSummary:
    """
    Generates demand forecasts and stockout predictions across all active products for a shop.
    Returns aggregated metrics and individual product forecast lists.
    """
    active_products = (
        db.query(Product)
        .filter(Product.shop_id == shop_id, Product.is_active == True)
        .order_by(Product.name.asc())
        .all()
    )

    now_dt = as_of_date or datetime.now(timezone.utc)
    product_forecasts: List[ProductDemandForecast] = []

    tier_1_cnt = 0
    tier_2_cnt = 0
    tier_3_cnt = 0
    out_of_stock_cnt = 0
    at_risk_7d_cnt = 0

    for prod in active_products:
        forecast = forecast_product_demand(
            db=db,
            shop_id=shop_id,
            product_id=prod.id,
            as_of_date=now_dt,
            lead_time_days=lead_time_days,
            safety_stock=safety_stock,
            alpha=alpha,
            include_zero_price=include_zero_price,
        )
        product_forecasts.append(forecast)

        if forecast.forecast_tier == ForecastTier.TIER_1_SUFFICIENT:
            tier_1_cnt += 1
        elif forecast.forecast_tier == ForecastTier.TIER_2_SPARSE:
            tier_2_cnt += 1
        elif forecast.forecast_tier == ForecastTier.TIER_3_COLD_START:
            tier_3_cnt += 1

        if forecast.current_stock <= 0:
            out_of_stock_cnt += 1
        elif forecast.days_to_stockout is not None and forecast.days_to_stockout <= 7.0:
            at_risk_7d_cnt += 1

    return ShopForecastSummary(
        shop_id=shop_id,
        generated_at=now_dt.isoformat(),
        total_products_analyzed=len(active_products),
        tier_1_count=tier_1_cnt,
        tier_2_count=tier_2_cnt,
        tier_3_count=tier_3_cnt,
        out_of_stock_count=out_of_stock_cnt,
        at_risk_stockout_7d_count=at_risk_7d_cnt,
        forecasts=product_forecasts,
    )


class ForecastCache:
    """
    Thread-safe, tenant-isolated in-memory cache for ShopPulse demand forecasts.
    Guarantees strict shop isolation, prevents unbounded stale inventory via TTL,
    and supports explicit per-shop invalidation on mutation events.
    """
    def __init__(self, ttl_seconds: int = 60):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.ttl_seconds = ttl_seconds

    def _build_key(self, shop_id: UUID, key: str) -> str:
        return f"{shop_id}:{key}"

    def get(self, shop_id: UUID, key: str) -> Optional[Any]:
        full_key = self._build_key(shop_id, key)
        with self._lock:
            entry = self._cache.get(full_key)
            if not entry:
                return None
            cached_time, val = entry
            if time.time() - cached_time > self.ttl_seconds:
                del self._cache[full_key]
                return None
            return val

    def set(self, shop_id: UUID, key: str, value: Any) -> None:
        full_key = self._build_key(shop_id, key)
        with self._lock:
            self._cache[full_key] = (time.time(), value)

    def invalidate_shop(self, shop_id: UUID) -> int:
        prefix = f"{shop_id}:"
        with self._lock:
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._cache[k]
            return len(keys_to_delete)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)


_global_forecast_cache = ForecastCache(ttl_seconds=60)


def get_forecast_cache() -> ForecastCache:
    return _global_forecast_cache


def invalidate_forecast_cache(shop_id: Optional[UUID] = None) -> int:
    """
    Invalidates cached demand forecasts.
    If shop_id is provided, only entries for that specific tenant are evicted.
    If shop_id is None, clears all cached entries across all tenants.
    """
    if shop_id:
        return _global_forecast_cache.invalidate_shop(shop_id)
    _global_forecast_cache.clear()
    return 0

