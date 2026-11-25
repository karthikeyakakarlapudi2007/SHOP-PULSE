from typing import Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api import deps
from db.models.user import User
from schemas.notification import (
    NotificationResponse,
    PaginatedNotificationResponse,
    UnreadCountResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    DeviceTokenRegister,
    DeviceTokenResponse,
)
from services import shop as shop_service
from services import notification as notif_service

router = APIRouter()

def get_user_shop_or_raise(db: Session, user: User):
    shop = deps.get_user_accessible_shop(db, user)
    if not shop:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must create or join a shop profile before managing notifications.",
        )
    return shop


@router.get("", response_model=PaginatedNotificationResponse)
@router.get("/", response_model=PaginatedNotificationResponse, include_in_schema=False)
def list_notifications(
    *,
    db: Session = Depends(deps.get_db),
    category: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    is_read: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Fetch paginated notifications with optional category/priority/read filters for the shop.
    """
    shop = get_user_shop_or_raise(db, current_user)
    items, total, unread = notif_service.get_notifications(
        db,
        shop_id=shop.id,
        category=category,
        priority=priority,
        is_read=is_read,
        skip=skip,
        limit=limit
    )
    return PaginatedNotificationResponse(
        items=items,
        total=total,
        unread_count=unread,
        skip=skip,
        limit=limit
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Fetch total unread notifications count for header badge.
    """
    shop = get_user_shop_or_raise(db, current_user)
    count = notif_service.get_unread_count(db, shop_id=shop.id)
    return UnreadCountResponse(count=count)


@router.patch("/{id}/read", response_model=NotificationResponse)
def mark_notification_read(
    *,
    db: Session = Depends(deps.get_db),
    id: UUID,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Mark an individual notification as read.
    """
    shop = get_user_shop_or_raise(db, current_user)
    notif = notif_service.mark_as_read(db, shop_id=shop.id, notification_id=id)
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    return notif


@router.post("/mark-all-read")
def mark_all_read(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Mark all unread notifications for the shop as read.
    """
    shop = get_user_shop_or_raise(db, current_user)
    count = notif_service.mark_all_as_read(db, shop_id=shop.id)
    return {"message": "All notifications marked as read", "marked_count": count}


@router.delete("/{id}")
def delete_notification(
    *,
    db: Session = Depends(deps.get_db),
    id: UUID,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Delete a notification.
    """
    shop = get_user_shop_or_raise(db, current_user)
    success = notif_service.delete_notification(db, shop_id=shop.id, notification_id=id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    return {"message": "Notification deleted successfully"}


@router.get("/preferences", response_model=NotificationPreferenceResponse)
def get_preferences(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Fetch user notification preferences.
    """
    shop = get_user_shop_or_raise(db, current_user)
    return notif_service.get_or_create_preferences(db, user_id=current_user.id, shop_id=shop.id)


@router.put("/preferences", response_model=NotificationPreferenceResponse)
def update_preferences(
    *,
    db: Session = Depends(deps.get_db),
    preferences_in: NotificationPreferenceUpdate,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Update user notification preferences.
    """
    shop = get_user_shop_or_raise(db, current_user)
    return notif_service.update_preferences(
        db,
        user_id=current_user.id,
        shop_id=shop.id,
        update_data=preferences_in
    )


@router.post("/devices", response_model=DeviceTokenResponse)
def register_device(
    *,
    db: Session = Depends(deps.get_db),
    device_in: DeviceTokenRegister,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Register or reactivate mobile device token for push notifications.
    """
    return notif_service.register_device_token(
        db,
        user_id=current_user.id,
        reg_in=device_in
    )


@router.delete("/devices/{token}")
def unregister_device(
    *,
    db: Session = Depends(deps.get_db),
    token: str,
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Unregister mobile push device token.
    """
    success = notif_service.unregister_device_token(db, user_id=current_user.id, token=token)
    return {"message": "Device token unregistered", "success": success}


@router.post("/trigger-evaluation")
def trigger_notification_evaluation(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Explicitly trigger event detection engine for inventory and sales alerts.
    """
    shop = get_user_shop_or_raise(db, current_user)
    emitted = notif_service.evaluate_shop_notifications(
        db,
        shop_id=shop.id,
        user_id=current_user.id
    )
    return {
        "message": "Evaluation completed",
        "alerts_generated": len(emitted),
        "notifications": [NotificationResponse.model_validate(n) for n in emitted]
    }

