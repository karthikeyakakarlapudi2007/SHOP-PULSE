from typing import Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.orm import Session

from api import deps
from db.models.shop import Shop
from db.models.shop_member import ShopMember, ShopRole
from schemas.supplier import (
    SupplierCreate,
    SupplierUpdate,
    SupplierResponse,
    PaginatedSupplierResponse,
)
from services import supplier as supplier_service

router = APIRouter()

@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_supplier(
    *,
    db: Session = Depends(deps.get_db),
    supplier_in: SupplierCreate,
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Create a new supplier for the authenticated user's shop.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    return supplier_service.create_supplier(db, supplier_in=supplier_in, shop_id=user_shop.id)

@router.get("", response_model=PaginatedSupplierResponse)
@router.get("/", response_model=PaginatedSupplierResponse, include_in_schema=False)
def get_suppliers(
    *,
    db: Session = Depends(deps.get_db),
    search: Optional[str] = Query(None, description="Search by supplier name"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get paginated list of suppliers for the authenticated user's shop.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    items, total = supplier_service.get_suppliers_by_shop(
        db, shop_id=user_shop.id, search=search, skip=skip, limit=limit
    )
    return PaginatedSupplierResponse(items=items, total=total, skip=skip, limit=limit)

@router.get("/{id}", response_model=SupplierResponse)
def get_supplier(
    *,
    db: Session = Depends(deps.get_db),
    id: UUID,
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Get supplier details by ID.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    supplier = supplier_service.get_supplier_by_id(db, supplier_id=id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found.",
        )
    if supplier.shop_id != user_shop.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this supplier.",
        )
    return supplier

@router.put("/{id}", response_model=SupplierResponse)
def update_supplier(
    *,
    db: Session = Depends(deps.get_db),
    id: UUID,
    supplier_in: SupplierUpdate,
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Any:
    """
    Update supplier details by ID.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    supplier = supplier_service.get_supplier_by_id(db, supplier_id=id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found.",
        )
    if supplier.shop_id != user_shop.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this supplier.",
        )
    return supplier_service.update_supplier(db, db_supplier=supplier, supplier_in=supplier_in)

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier(
    *,
    db: Session = Depends(deps.get_db),
    id: UUID,
    auth_context: tuple[Shop, ShopMember] = Depends(deps.require_roles([ShopRole.OWNER.value, ShopRole.MANAGER.value])),
) -> Response:
    """
    Delete a supplier by ID.
    Restricted to Owner and Manager roles.
    """
    user_shop, _ = auth_context
    supplier = supplier_service.get_supplier_by_id(db, supplier_id=id)
    if not supplier:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found.",
        )
    if supplier.shop_id != user_shop.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this supplier.",
        )
    supplier_service.delete_supplier(db, db_supplier=supplier)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
