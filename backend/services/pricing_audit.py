from typing import Optional, List, Tuple
from uuid import UUID
from sqlalchemy.orm import Session

from db.models.pricing_audit_log import PricingAuditLog


def create_pricing_audit_log(
    db: Session,
    shop_id: UUID,
    acting_user_id: UUID,
    action_type: str,
    product_id: UUID,
    previous_status: Optional[str] = None,
    new_status: Optional[str] = None,
    previous_selling_price: Optional[float] = None,
    new_selling_price: Optional[float] = None,
    previous_mrp: Optional[float] = None,
    new_mrp: Optional[float] = None,
    invoice_number: Optional[str] = None,
    reason: Optional[str] = None,
) -> PricingAuditLog:
    """Create an immutable server-side audit trail record for product pricing and verification changes."""
    log = PricingAuditLog(
        shop_id=shop_id,
        acting_user_id=acting_user_id,
        action_type=action_type,
        product_id=product_id,
        previous_status=previous_status,
        new_status=new_status,
        previous_selling_price=previous_selling_price,
        new_selling_price=new_selling_price,
        previous_mrp=previous_mrp,
        new_mrp=new_mrp,
        invoice_number=invoice_number,
        reason=reason,
    )
    db.add(log)
    db.flush()
    return log


def get_product_audit_logs(
    db: Session,
    shop_id: UUID,
    product_id: UUID
) -> List[PricingAuditLog]:
    """Retrieve audit history for a specific product within the shop, most recent first."""
    return db.query(PricingAuditLog).filter(
        PricingAuditLog.shop_id == shop_id,
        PricingAuditLog.product_id == product_id
    ).order_by(PricingAuditLog.created_at.desc()).all()


def get_shop_pricing_audit_logs(
    db: Session,
    shop_id: UUID,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[PricingAuditLog], int]:
    """Retrieve paginated pricing audit history for the shop, most recent first."""
    query = db.query(PricingAuditLog).filter(PricingAuditLog.shop_id == shop_id)
    total = query.count()
    items = query.order_by(PricingAuditLog.created_at.desc()).offset(skip).limit(limit).all()
    return items, total
