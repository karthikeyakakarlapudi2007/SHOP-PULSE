from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import deps
from db.models.product import Product
from db.models.shop import Shop
from db.models.shop_member import ShopMember, ShopRole
from schemas.forecast import (
    ConfidenceLevel,
    ForecastStatus,
    ForecastTier,
    ShopForecastSummary,
)
from schemas.insights import (
    SalesInsightsResponse,
    InventoryInsightsResponse,
    AiInsightsResponse,
)
from services import insights as insights_service
from services.forecasting import (
    forecast_product_demand,
    forecast_shop_demand,
    get_forecast_cache,
)

router = APIRouter()


@router.get("/sales", response_model=SalesInsightsResponse)
def get_sales_insights(
    *,
    db: Session = Depends(deps.get_db),
    period: str = Query("7d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get deterministic sales overview, product performance rankings, and daily trends.
    Restricted to Owner and Manager roles.
    """
    shop, _ = auth_context
    return insights_service.get_sales_insights(
        db,
        shop_id=shop.id,
        period=period,
        start_date_str=start_date,
        end_date_str=end_date
    )


@router.get("/inventory", response_model=InventoryInsightsResponse)
def get_inventory_insights(
    *,
    db: Session = Depends(deps.get_db),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get deterministic inventory breakdown: in stock, low stock, out of stock, overstocked.
    Restricted to Owner and Manager roles.
    """
    shop, _ = auth_context
    return insights_service.get_inventory_insights(db, shop_id=shop.id)


@router.get("/ai-summary", response_model=AiInsightsResponse)
def get_ai_insights(
    *,
    db: Session = Depends(deps.get_db),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get AI-generated narrative business explanations grounded entirely in database figures.
    Restricted to Owner and Manager roles.
    """
    shop, _ = auth_context
    return insights_service.get_ai_insights(db, shop_id=shop.id)


@router.get("/demand-forecast", response_model=ShopForecastSummary)
def get_demand_forecast(
    *,
    db: Session = Depends(deps.get_db),
    product_id: Optional[UUID] = Query(None, description="Filter forecast for a specific product ID"),
    forecast_tier: Optional[ForecastTier] = Query(None, description="Filter by forecast tier"),
    forecast_status: Optional[ForecastStatus] = Query(None, description="Filter by forecast status"),
    confidence_level: Optional[ConfidenceLevel] = Query(None, description="Filter by confidence level"),
    lead_time_days: int = Query(3, ge=1, le=90, description="Lead time in days for reorder calculation"),
    alpha: float = Query(0.3, gt=0.0, lt=1.0, description="EWMA smoothing factor"),
    include_zero_price: bool = Query(True, description="Include zero-price promotional items"),
    no_cache: bool = Query(False, description="Bypass cache and force fresh database computation"),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get deterministic demand forecasting, stockout predictions, and reorder recommendations.
    Restricted to Owner and Manager roles for their active authorized shop.
    Guarantees strict tenant isolation, validation of query parameters, and in-memory cache invalidation.
    """
    shop, _ = auth_context
    forecast_cache = get_forecast_cache()

    cache_key = (
        f"{product_id}:{forecast_tier}:{forecast_status}:{confidence_level}:"
        f"{lead_time_days}:{alpha}:{include_zero_price}"
    )

    if not no_cache:
        cached = forecast_cache.get(shop.id, cache_key)
        if cached is not None:
            return cached

    # Case 1: Specific product requested
    if product_id is not None:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product or product.shop_id != shop.id:
            # Prevent leaking existence of products in other tenant shops
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product '{product_id}' not found.",
            )
        if not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product '{product_id}' is inactive.",
            )

        prod_forecast = forecast_product_demand(
            db=db,
            shop_id=shop.id,
            product_id=product.id,
            lead_time_days=lead_time_days,
            alpha=alpha,
            include_zero_price=include_zero_price,
        )

        matches = True
        if forecast_tier and prod_forecast.forecast_tier != forecast_tier:
            matches = False
        if forecast_status and prod_forecast.forecast_status != forecast_status:
            matches = False
        if confidence_level and prod_forecast.confidence_level != confidence_level:
            matches = False

        forecast_list = [prod_forecast] if matches else []

        result = ShopForecastSummary(
            shop_id=shop.id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_products_analyzed=1,
            tier_1_count=1 if prod_forecast.forecast_tier == ForecastTier.TIER_1_SUFFICIENT else 0,
            tier_2_count=1 if prod_forecast.forecast_tier == ForecastTier.TIER_2_SPARSE else 0,
            tier_3_count=1 if prod_forecast.forecast_tier == ForecastTier.TIER_3_COLD_START else 0,
            out_of_stock_count=1 if prod_forecast.current_stock <= 0 else 0,
            at_risk_stockout_7d_count=(
                1 if prod_forecast.days_to_stockout is not None and prod_forecast.days_to_stockout <= 7.0 else 0
            ),
            forecasts=forecast_list,
        )

    # Case 2: Entire active product catalog for shop
    else:
        shop_summary = forecast_shop_demand(
            db=db,
            shop_id=shop.id,
            lead_time_days=lead_time_days,
            alpha=alpha,
            include_zero_price=include_zero_price,
        )

        filtered_forecasts = shop_summary.forecasts
        if forecast_tier:
            filtered_forecasts = [f for f in filtered_forecasts if f.forecast_tier == forecast_tier]
        if forecast_status:
            filtered_forecasts = [f for f in filtered_forecasts if f.forecast_status == forecast_status]
        if confidence_level:
            filtered_forecasts = [f for f in filtered_forecasts if f.confidence_level == confidence_level]

        result = ShopForecastSummary(
            shop_id=shop.id,
            generated_at=shop_summary.generated_at,
            total_products_analyzed=shop_summary.total_products_analyzed,
            tier_1_count=shop_summary.tier_1_count,
            tier_2_count=shop_summary.tier_2_count,
            tier_3_count=shop_summary.tier_3_count,
            out_of_stock_count=shop_summary.out_of_stock_count,
            at_risk_stockout_7d_count=shop_summary.at_risk_stockout_7d_count,
            forecasts=filtered_forecasts,
        )

    if not no_cache:
        forecast_cache.set(shop.id, cache_key, result)

    return result

