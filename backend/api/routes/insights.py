from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import deps
from db.models.user import User
from schemas.insights import (
    SalesInsightsResponse,
    InventoryInsightsResponse,
    AiInsightsResponse,
)
from services import shop as shop_service
from services import insights as insights_service

router = APIRouter()

def get_user_shop_or_raise(db: Session, user: User):
    shop = shop_service.get_shop_by_owner(db, owner_id=user.id)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must create a shop profile before accessing insights.",
        )
    return shop


@router.get("/sales", response_model=SalesInsightsResponse)
def get_sales_insights(
    *,
    db: Session = Depends(deps.get_db),
    period: str = Query("7d", pattern="^(today|7d|30d|90d|custom)$"),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get deterministic sales overview, product performance rankings, and daily trends.
    """
    shop = get_user_shop_or_raise(db, current_user)
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
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get deterministic inventory breakdown: in stock, low stock, out of stock, overstocked.
    """
    shop = get_user_shop_or_raise(db, current_user)
    return insights_service.get_inventory_insights(db, shop_id=shop.id)


@router.get("/ai-summary", response_model=AiInsightsResponse)
def get_ai_insights(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get AI-generated narrative business explanations grounded entirely in database figures.
    """
    shop = get_user_shop_or_raise(db, current_user)
    return insights_service.get_ai_insights(db, shop_id=shop.id)
