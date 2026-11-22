from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from schemas.quantity import Quantity

class SaleItemCreate(BaseModel):
    product_id: UUID = Field(..., description="Product ID to sell")
    quantity: Quantity = Field(..., gt=0, description="Quantity to sell (> 0; fractional only for kg, g, L, ml)")
    unit: Optional[str] = Field(None, description="Requested unit of the quantity (defaults to product inventory unit if omitted)")
    unit_price: Optional[float] = Field(None, ge=0, description="Optional client price assertion. Validated against catalog pricing; never replaces server-authoritative calculation.")

class SaleCreate(BaseModel):
    items: List[SaleItemCreate] = Field(..., min_length=1, description="Sale item lines")
    payment_method: str = Field("cash", description="Payment method (cash, upi, card, credit)")
    customer_name: Optional[str] = Field(None, description="Optional counter customer name")

class SaleItemResponse(BaseModel):
    id: UUID
    sale_id: UUID
    product_id: UUID
    quantity: Quantity
    unit_price: float
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class SaleResponse(BaseModel):
    id: UUID
    shop_id: UUID
    total_amount: float
    payment_method: str
    items: List[SaleItemResponse]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class PaginatedSaleResponse(BaseModel):
    items: List[SaleResponse]
    total: int
    skip: int
    limit: int
