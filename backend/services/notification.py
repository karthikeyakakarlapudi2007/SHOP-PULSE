import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_

from db.models.notification import Notification, NotificationPreference, DeviceToken
from db.models.product import Product
from db.models.sale import Sale
from db.models.user import User
from services.money import round_currency, sum_decimal
from services.stock import quantity_number
from schemas.notification import (
    NotificationCreate,
    NotificationPreferenceUpdate,
    DeviceTokenRegister,
)

logger = logging.getLogger(__name__)

def get_or_create_preferences(db: Session, user_id: UUID, shop_id: UUID) -> NotificationPreference:
    pref = db.query(NotificationPreference).filter(NotificationPreference.user_id == user_id).first()
    if not pref:
        pref = NotificationPreference(
            user_id=user_id,
            shop_id=shop_id,
            sales_alerts=True,
            inventory_alerts=True,
            system_alerts=True,
            in_app_enabled=True,
            push_enabled=True,
            daily_summary_enabled=True
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


def update_preferences(
    db: Session,
    user_id: UUID,
    shop_id: UUID,
    update_data: NotificationPreferenceUpdate
) -> NotificationPreference:
    pref = get_or_create_preferences(db, user_id, shop_id)
    pref.sales_alerts = update_data.sales_alerts
    pref.inventory_alerts = update_data.inventory_alerts
    pref.system_alerts = update_data.system_alerts
    pref.in_app_enabled = update_data.in_app_enabled
    pref.push_enabled = update_data.push_enabled
    pref.daily_summary_enabled = update_data.daily_summary_enabled
    db.commit()
    db.refresh(pref)
    return pref


def create_notification(
    db: Session,
    notif_in: NotificationCreate,
    cooldown_hours: int = 24
) -> Optional[Notification]:
    """
    Creates a notification with user preference checks, duplicate de-duplication,
    cooldown enforcement, and mock push dispatch.
    """
    pref = get_or_create_preferences(db, notif_in.user_id, notif_in.shop_id)

    # Check if category is enabled in user preferences
    if not pref.in_app_enabled:
        return None
    if notif_in.category == "inventory" and not pref.inventory_alerts:
        return None
    if notif_in.category == "sales" and not pref.sales_alerts:
        return None
    if notif_in.category == "system" and not pref.system_alerts:
        return None

    now = datetime.now(timezone.utc)
    now_naive = now.replace(tzinfo=None)

    # De-duplication check based on event_key within cooldown window
    if notif_in.event_key:
        cooldown_cutoff = now - timedelta(hours=cooldown_hours)
        cooldown_cutoff_naive = cooldown_cutoff.replace(tzinfo=None)
        
        existing = (
            db.query(Notification)
            .filter(
                Notification.shop_id == notif_in.shop_id,
                Notification.event_key == notif_in.event_key,
                or_(
                    Notification.created_at >= cooldown_cutoff,
                    Notification.created_at >= cooldown_cutoff_naive
                )
            )
            .first()
        )
        if existing:
            # Duplicate within cooldown; do not re-emit
            return None

    db_notif = Notification(
        user_id=notif_in.user_id,
        shop_id=notif_in.shop_id,
        title=notif_in.title,
        message=notif_in.message,
        category=notif_in.category,
        priority=notif_in.priority,
        is_read=False,
        product_id=notif_in.product_id,
        transaction_id=notif_in.transaction_id,
        deep_link=notif_in.deep_link,
        event_key=notif_in.event_key,
    )
    db.add(db_notif)
    db.commit()
    db.refresh(db_notif)

    # Dispatch mobile push notification if enabled
    if pref.push_enabled:
        _dispatch_push_alert(db, notif_in.user_id, db_notif)

    return db_notif


def _dispatch_push_alert(db: Session, user_id: UUID, notif: Notification) -> None:
    """
    Safely delivers push alerts to registered active devices.
    Catches and logs all errors so push delivery issues never block database transactions.
    """
    try:
        devices = (
            db.query(DeviceToken)
            .filter(DeviceToken.user_id == user_id, DeviceToken.is_active == True)
            .all()
        )
        for dev in devices:
            logger.info(
                "[PushNotification] Dispatched %s to device %s (%s): %s",
                notif.priority,
                dev.token[:12] + "...",
                dev.platform,
                notif.title
            )
    except Exception as exc:
        logger.warning("[PushNotification] Dispatch exception safely caught: %s", exc)


def evaluate_shop_notifications(
    db: Session,
    shop_id: UUID,
    user_id: UUID
) -> List[Notification]:
    """
    Analyzes actual database state to emit inventory and sales notifications.
    Safe against multiple refreshes due to event_key cooldown de-duplication.
    """
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    emitted: List[Notification] = []

    # 1. Evaluate Inventory Conditions
    products = (
        db.query(Product)
        .filter(Product.shop_id == shop_id, Product.is_active == True)
        .all()
    )

    for p in products:
        stock = quantity_number(p.current_stock)  # fractional stock is never truncated
        reorder = quantity_number(p.reorder_level) if (p.reorder_level is not None) else 0
        has_threshold = p.reorder_level is not None and p.reorder_level > 0

        if stock <= 0:
            notif = create_notification(
                db,
                NotificationCreate(
                    user_id=user_id,
                    shop_id=shop_id,
                    title=f"Out of Stock: {p.name}",
                    message=f"{p.name} has 0 {p.unit or 'units'} remaining in inventory. Immediate restock required.",
                    category="inventory",
                    priority="critical",
                    product_id=p.id,
                    deep_link=f"/inventory?id={p.id}",
                    event_key=f"out_of_stock:{p.id}:{today_str}"
                ),
                cooldown_hours=24
            )
            if notif:
                emitted.append(notif)
        elif has_threshold and stock <= reorder:
            notif = create_notification(
                db,
                NotificationCreate(
                    user_id=user_id,
                    shop_id=shop_id,
                    title=f"Low Stock Alert: {p.name}",
                    message=f"{p.name} has {stock} {p.unit or 'units'} remaining. Minimum configured threshold is {reorder} {p.unit or 'units'}.",
                    category="inventory",
                    priority="high",
                    product_id=p.id,
                    deep_link=f"/inventory?id={p.id}",
                    event_key=f"low_stock:{p.id}:{today_str}"
                ),
                cooldown_hours=24
            )
            if notif:
                emitted.append(notif)
        elif has_threshold and stock >= (reorder * 5) and stock >= 40:
            notif = create_notification(
                db,
                NotificationCreate(
                    user_id=user_id,
                    shop_id=shop_id,
                    title=f"Overstock Notice: {p.name}",
                    message=f"{p.name} has {stock} {p.unit or 'units'} in stock (5x reorder threshold). Review purchasing cadence.",
                    category="inventory",
                    priority="low",
                    product_id=p.id,
                    deep_link=f"/inventory?id={p.id}",
                    event_key=f"overstock:{p.id}:{today_str}"
                ),
                cooldown_hours=72
            )
            if notif:
                emitted.append(notif)
        elif stock > reorder:
            # Auto-resolve previously unresolved low-stock notifications for this product
            (
                db.query(Notification)
                .filter(
                    Notification.shop_id == shop_id,
                    Notification.product_id == p.id,
                    Notification.category == "inventory",
                    Notification.resolved_at.is_(None)
                )
                .update({"resolved_at": now}, synchronize_session=False)
            )
            db.commit()

    # 2. Evaluate Daily Sales Summary
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_naive = today_start.replace(tzinfo=None)

    # Bill totals summed in Decimal (no binary SQL SUM) and rounded half-up to paise
    today_sale_totals = (
        db.query(Sale.total_amount)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                Sale.created_at >= today_start,
                Sale.created_at >= today_start_naive
            )
        )
        .all()
    )
    today_sum = round_currency(sum_decimal(t for (t,) in today_sale_totals))
    today_tx = len(today_sale_totals)

    if today_tx > 0:
        notif = create_notification(
            db,
            NotificationCreate(
                user_id=user_id,
                shop_id=shop_id,
                title="Daily Sales Summary",
                message=f"Today's total sales reached ₹{today_sum:,.2f} across {today_tx} customer transactions.",
                category="sales",
                priority="medium",
                deep_link="/insights?tab=sales",
                event_key=f"daily_summary:{shop_id}:{today_str}"
            ),
            cooldown_hours=24
        )
        if notif:
            emitted.append(notif)

    return emitted


def get_notifications(
    db: Session,
    shop_id: UUID,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    is_read: Optional[bool] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[Notification], int, int]:
    query = db.query(Notification).filter(Notification.shop_id == shop_id)

    if category:
        query = query.filter(Notification.category == category)
    if priority:
        query = query.filter(Notification.priority == priority)
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)

    total = query.count()
    items = query.order_by(desc(Notification.created_at)).offset(skip).limit(limit).all()

    unread_count = (
        db.query(func.count(Notification.id))
        .filter(Notification.shop_id == shop_id, Notification.is_read == False)
        .scalar() or 0
    )

    return items, total, unread_count


def get_unread_count(db: Session, shop_id: UUID) -> int:
    return (
        db.query(func.count(Notification.id))
        .filter(Notification.shop_id == shop_id, Notification.is_read == False)
        .scalar() or 0
    )


def mark_as_read(db: Session, shop_id: UUID, notification_id: UUID) -> Optional[Notification]:
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.shop_id == shop_id)
        .first()
    )
    if not notif:
        return None
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


def mark_all_as_read(db: Session, shop_id: UUID) -> int:
    count = (
        db.query(Notification)
        .filter(Notification.shop_id == shop_id, Notification.is_read == False)
        .update({"is_read": True}, synchronize_session=False)
    )
    db.commit()
    return count


def delete_notification(db: Session, shop_id: UUID, notification_id: UUID) -> bool:
    notif = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.shop_id == shop_id)
        .first()
    )
    if not notif:
        return False
    db.delete(notif)
    db.commit()
    return True


def register_device_token(
    db: Session,
    user_id: UUID,
    reg_in: DeviceTokenRegister
) -> DeviceToken:
    existing = db.query(DeviceToken).filter(DeviceToken.token == reg_in.token).first()
    if existing:
        existing.user_id = user_id
        existing.platform = reg_in.platform or existing.platform
        existing.is_active = True
        db.commit()
        db.refresh(existing)
        return existing

    device = DeviceToken(
        user_id=user_id,
        token=reg_in.token,
        platform=reg_in.platform or "android",
        is_active=True
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def unregister_device_token(db: Session, user_id: UUID, token: str) -> bool:
    device = (
        db.query(DeviceToken)
        .filter(DeviceToken.token == token, DeviceToken.user_id == user_id)
        .first()
    )
    if not device:
        return False
    device.is_active = False
    db.commit()
    return True

