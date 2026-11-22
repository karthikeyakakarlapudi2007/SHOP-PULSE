import uuid
from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from db.session import Base

class PricingAuditLog(Base):
    __tablename__ = "pricing_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    shop_id = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True)
    acting_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False)  # "VERIFY_PRICING", "SELLING_PRICE_OVERRIDE"
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    previous_selling_price = Column(Float, nullable=True)
    new_selling_price = Column(Float, nullable=True)
    previous_mrp = Column(Float, nullable=True)
    new_mrp = Column(Float, nullable=True)
    invoice_number = Column(String(100), nullable=True)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    shop = relationship("Shop")
    acting_user = relationship("User")
    product = relationship("Product")
