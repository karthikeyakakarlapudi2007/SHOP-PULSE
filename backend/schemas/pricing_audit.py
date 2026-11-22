from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

class PricingAuditLogResponse(BaseModel):
    id: UUID
    shop_id: UUID
    acting_user_id: UUID
    action_type: str
    product_id: UUID
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    previous_selling_price: Optional[float] = None
    new_selling_price: Optional[float] = None
    previous_mrp: Optional[float] = None
    new_mrp: Optional[float] = None
    invoice_number: Optional[str] = None
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
