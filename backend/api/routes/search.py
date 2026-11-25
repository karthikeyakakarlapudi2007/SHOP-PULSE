from typing import Any
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api import deps
from db.models.user import User
from schemas.search import SearchResponse
from services import shop as shop_service
from services import search as search_service

router = APIRouter()


@router.get("", response_model=SearchResponse)
@router.get("/", response_model=SearchResponse, include_in_schema=False)
def search(
    *,
    db: Session = Depends(deps.get_db),
    q: str = Query(..., max_length=100, description="Text to find (at least 2 characters)"),
    limit: int = Query(5, ge=1, le=20, description="Maximum results per group"),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Search the authenticated user's shop for products (name, SKU, category), purchase invoices
    (invoice number, supplier, product on the invoice) and sales (bill number, product sold).
    Partial and case-insensitive. Queries shorter than 2 characters return no results.
    """
    shop = deps.get_user_accessible_shop(db, current_user)
    if not shop:
        return SearchResponse(query=q.strip())
    
    results = search_service.search_shop_records(db, shop_id=shop.id, query=q, limit=limit)
    member = deps.shop_member_service.get_shop_member(db, shop.id, current_user.id)
    if member and member.role == deps.ShopRole.CASHIER.value:
        # Cashiers cannot access supplier purchases
        results.purchases = []
        results.totals.purchases = 0
    return results
