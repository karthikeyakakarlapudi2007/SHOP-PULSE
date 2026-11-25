from typing import Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from api import deps
from db.models.shop import Shop
from db.models.shop_member import ShopMember, ShopRole
from schemas.purchase import (
    PurchaseCreate,
    PurchaseResponse,
    PaginatedPurchaseResponse,
)
from services import purchase as purchase_service
from services.forecasting import invalidate_forecast_cache

router = APIRouter()

@router.post("", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=PurchaseResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_purchase(
    *,
    db: Session = Depends(deps.get_db),
    purchase_in: PurchaseCreate,
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Log a new stock purchase, automatically increasing product inventory.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    try:
        purchase = purchase_service.create_purchase(db, purchase_in=purchase_in, shop_id=user_shop.id)
        invalidate_forecast_cache(user_shop.id)
        return purchase
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("", response_model=PaginatedPurchaseResponse)
@router.get("/", response_model=PaginatedPurchaseResponse, include_in_schema=False)
def get_purchases(
    *,
    db: Session = Depends(deps.get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get paginated purchase history for the authenticated user's shop.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    items, total = purchase_service.get_purchases_by_shop(
        db, shop_id=user_shop.id, skip=skip, limit=limit
    )
    return PaginatedPurchaseResponse(items=items, total=total, skip=skip, limit=limit)

@router.get("/{id}", response_model=PurchaseResponse)
def get_purchase(
    *,
    db: Session = Depends(deps.get_db),
    id: UUID,
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get purchase details by ID, including item lines.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    purchase = purchase_service.get_purchase_by_id(db, purchase_id=id)
    if not purchase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Purchase record not found.",
        )
    if purchase.shop_id != user_shop.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this purchase record.",
        )
    return purchase
