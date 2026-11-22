from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, computed_field
from schemas.quantity import Quantity

class PurchaseItemCreate(BaseModel):
    product_id: UUID = Field(..., description="Product ID to purchase")
    quantity: Quantity = Field(..., gt=0, description="Quantity purchased (> 0; fractional only for kg, g, L, ml)")
    unit: Optional[str] = Field(None, description="Unit of the quantity when it differs from the product unit (e.g. g for a kg product)")
    purchase_price: float = Field(..., ge=0, description="Unit purchase price (must be >= 0)")
    price_basis_quantity: Optional[float] = Field(1.0, gt=0, description="Reference quantity for purchase_price (default 1.0)")
    price_basis_unit: Optional[str] = Field(None, description="Canonical unit in which purchase_price is quoted")

class PurchaseCreate(BaseModel):
    supplier_id: Optional[UUID] = Field(None, description="Optional Supplier ID")
    items: List[PurchaseItemCreate] = Field(..., min_length=1, description="Purchase item lines")

class PurchaseItemResponse(BaseModel):
    id: UUID
    purchase_id: UUID
    product_id: UUID
    quantity: Quantity
    purchase_price: float
    price_basis_quantity: Optional[float] = 1.0
    price_basis_unit: Optional[str] = None
    # Additional read-only details for viewing/printing a purchase record
    product_name: Optional[str] = None
    product_unit: Optional[str] = None
    line_amount: Optional[float] = None
    mrp: Optional[float] = None
    mrp_source: Optional[str] = None
    created_at: Optional[datetime] = None

    @computed_field
    @property
    def normalized_purchase_price(self) -> Optional[float]:
        """Normalized purchase price per single base unit or inventory unit."""
        if self.purchase_price is None:
            return None
        basis_qty = self.price_basis_quantity if self.price_basis_quantity is not None else 1.0
        if float(basis_qty) <= 0:
            return float(self.purchase_price)
        return round(float(self.purchase_price) / float(basis_qty), 3)

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
