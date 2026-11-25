from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import deps
from db.models.shop import Shop
from db.models.shop_member import ShopMember, ShopRole
from schemas.dashboard import DashboardResponse
from services import dashboard as dashboard_service

router = APIRouter()

@router.get("", response_model=DashboardResponse)
@router.get("/", response_model=DashboardResponse, include_in_schema=False)
def get_dashboard(
    *,
    db: Session = Depends(deps.get_db),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Fetch comprehensive dashboard information for the authenticated shop owner or manager.
    Single endpoint optimized for mobile devices. Restricted to Owner and Manager roles.
    """
    shop, _ = auth_context
    return dashboard_service.get_dashboard_data(db, shop_id=shop.id)
