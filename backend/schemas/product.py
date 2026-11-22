from typing import Optional, List, Literal
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, computed_field
from schemas.quantity import Quantity

MrpSource = Literal["INVOICE", "API", "MANUAL", "STORE"]

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, description="Product name")
    category: Optional[str] = Field(None, description="Product category")
    selling_price: float = Field(..., ge=0, description="Selling price (must be >= 0)")
    purchase_price: Optional[float] = Field(0.0, ge=0, description="Purchase price (must be >= 0)")
    mrp: Optional[float] = Field(None, ge=0, description="Maximum retail price (must be >= 0)")
    current_stock: Quantity = Field(0, ge=0, description="Current stock in the product unit (>= 0; up to 3 decimals for kg, g, L, ml)")
    reorder_level: Optional[Quantity] = Field(0, ge=0, description="Reorder level in the product unit (>= 0)")
    unit: Optional[str] = Field("pcs", description="Unit of measurement")
    price_basis_quantity: Optional[float] = Field(1.0, gt=0, description="Reference quantity for which selling_price is quoted (default 1.0)")
    price_basis_unit: Optional[str] = Field(None, description="Canonical unit in which selling_price is quoted (e.g. kg, g, pcs)")
    mrp_basis_quantity: Optional[float] = Field(None, gt=0, description="Reference quantity for which MRP is quoted (defaults to price_basis_quantity if null)")
    mrp_basis_unit: Optional[str] = Field(None, description="Canonical unit in which MRP is quoted (defaults to price_basis_unit if null)")
    pricing_status: Optional[str] = Field("NEEDS_REVIEW", description="Pricing lifecycle status: VERIFIED | NEEDS_REVIEW | INCOMPLETE | WHOLESALE_ONLY")
    supplier_id: Optional[UUID] = Field(None, description="Supplier ID")
    sku: Optional[str] = Field(None, description="SKU or Barcode")
    is_active: bool = Field(True, description="Whether product is active in catalog")

class ProductCreate(ProductBase):
    mrp_source: Optional[MrpSource] = Field(None, description="Origin of the MRP value; defaults to MANUAL when an MRP is given")

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = None
    selling_price: Optional[float] = Field(None, ge=0)
    purchase_price: Optional[float] = Field(None, ge=0)
    mrp: Optional[float] = Field(None, ge=0)
    mrp_source: Optional[MrpSource] = None
    current_stock: Optional[Quantity] = Field(None, ge=0)
    reorder_level: Optional[Quantity] = Field(None, ge=0)
    unit: Optional[str] = None
    price_basis_quantity: Optional[float] = Field(None, gt=0)
    price_basis_unit: Optional[str] = None
    mrp_basis_quantity: Optional[float] = Field(None, gt=0)
    mrp_basis_unit: Optional[str] = None
    pricing_status: Optional[str] = Field(None, description="Deprecated; cannot be changed via standard product update")
    supplier_id: Optional[UUID] = None
    sku: Optional[str] = None
    is_active: Optional[bool] = None

class ProductVerifyRequest(BaseModel):
    reason: Optional[str] = Field(None, description="Reason or justification for pricing verification")

class ProductResponse(ProductBase):
    id: UUID
    shop_id: UUID
    mrp_source: Optional[str] = None
    mrp_updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @computed_field
    @property
    def stock_status(self) -> str:
        r_level = self.reorder_level if self.reorder_level is not None else 0
        if self.current_stock <= 0:
            return "Critical"
        if self.current_stock <= r_level:
            if r_level > 0 and self.current_stock <= (r_level // 2):
                return "Critical"
            return "Low Stock"
        return "In Stock"

    model_config = ConfigDict(from_attributes=True)

class PaginatedProductResponse(BaseModel):
    items: List[ProductResponse]
    total: int
    skip: int
    limit: int

class ProductLookupResponse(BaseModel):
    found: bool = Field(False, description="Whether product was matched")
    name: Optional[str] = Field(None, description="Product name")
    barcode: Optional[str] = Field(None, description="Barcode or SKU")
    unit: Optional[str] = Field(None, description="Packaging unit")
    purchase_price: Optional[float] = Field(None, description="Wholesale/purchase price (never substituted for MRP)")
    selling_price: Optional[float] = Field(None, description="Retail selling price")
    mrp: Optional[float] = Field(None, description="Maximum Retail Price (MRP)")
    mrp_source: Optional[str] = Field(None, description="Origin of the stored MRP for shop products")
    mrp_lookup_status: Optional[str] = Field(None, description="External MRP lookup status when the provider was queried")
    source: str = Field("NONE", description="Source: 'SHOP_INVENTORY', external provider name, or 'NONE'")
    confidence: float = Field(0.0, description="Match confidence score (0.0 - 1.0)")
    matched_product_id: Optional[UUID] = Field(None, description="Matched database product ID if from local shop")
    notes: Optional[str] = Field(None, description="Contextual or statutory notes")

