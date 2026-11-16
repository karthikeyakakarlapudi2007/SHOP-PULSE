from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class NotificationBase(BaseModel):
    title: str = Field(..., max_length=255)
    message: str = Field(..., max_length=1000)
    category: str = Field("inventory", max_length=50)  # inventory, sales, system
    priority: str = Field("medium", max_length=20)     # low, medium, high, critical
    product_id: Optional[UUID] = None
    transaction_id: Optional[UUID] = None
    deep_link: Optional[str] = None
    event_key: Optional[str] = None


class NotificationCreate(NotificationBase):
    user_id: UUID
    shop_id: UUID


class NotificationResponse(NotificationBase):
    id: UUID
    user_id: UUID
    shop_id: UUID
    is_read: bool
    created_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PaginatedNotificationResponse(BaseModel):
    items: List[NotificationResponse]
    total: int
    unread_count: int
    skip: int
    limit: int


class UnreadCountResponse(BaseModel):
    count: int


class NotificationPreferenceBase(BaseModel):
    sales_alerts: bool = True
    inventory_alerts: bool = True
    system_alerts: bool = True
    in_app_enabled: bool = True
    push_enabled: bool = True
    daily_summary_enabled: bool = True


class NotificationPreferenceUpdate(NotificationPreferenceBase):
    pass


class NotificationPreferenceResponse(NotificationPreferenceBase):
    id: UUID
    user_id: UUID
    shop_id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DeviceTokenRegister(BaseModel):
    token: str = Field(..., min_length=1, max_length=500)
    platform: Optional[str] = Field("android", max_length=50)


class DeviceTokenResponse(BaseModel):
    id: UUID
    user_id: UUID
    token: str
    platform: str
    is_active: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

