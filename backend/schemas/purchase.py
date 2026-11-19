from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from schemas.quantity import Quantity

class PurchaseItemCreate(BaseModel):
    product_id: UUID = Field(..., description="Product ID to purchase")
    quantity: Quantity = Field(..., gt=0, description="Quantity purchased (> 0; fractional only for kg, g, L, ml)")
    unit: Optional[str] = Field(None, description="Unit of the quantity when it differs from the product unit (e.g. g for a kg product)")
    purchase_price: float = Field(..., ge=0, description="Unit purchase price (must be >= 0)")

class PurchaseCreate(BaseModel):
    supplier_id: Optional[UUID] = Field(None, description="Optional Supplier ID")
    items: List[PurchaseItemCreate] = Field(..., min_length=1, description="Purchase item lines")

class PurchaseItemResponse(BaseModel):
    id: UUID
    purchase_id: UUID
    product_id: UUID
    quantity: Quantity
    purchase_price: float
    # Additional read-only details for viewing/printing a purchase record
    product_name: Optional[str] = None
    product_unit: Optional[str] = None
    line_amount: Optional[float] = None
    mrp: Optional[float] = None
    mrp_source: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class PurchaseResponse(BaseModel):
    id: UUID
    shop_id: UUID
    supplier_id: Optional[UUID] = None
    supplier_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total_amount: float
    items: List[PurchaseItemResponse]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class PaginatedPurchaseResponse(BaseModel):
    items: List[PurchaseResponse]
    total: int
    skip: int
    limit: int
