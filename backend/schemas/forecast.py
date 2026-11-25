from enum import Enum
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class ForecastTier(str, Enum):
    TIER_1_SUFFICIENT = "TIER_1_SUFFICIENT"
    TIER_2_SPARSE = "TIER_2_SPARSE"
    TIER_3_COLD_START = "TIER_3_COLD_START"


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"


class ForecastStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    LOW_STOCK = "LOW_STOCK"
    SPARSE_HISTORY = "SPARSE_HISTORY"
    NEW_PRODUCT_NO_SALES_HISTORY = "NEW_PRODUCT_NO_SALES_HISTORY"
    UNIT_REVIEW_REQUIRED = "UNIT_REVIEW_REQUIRED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


class ProductDemandForecast(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: UUID
    product_name: str
    current_stock: float
    normalized_unit: str
    total_valid_sales: int
    observable_days: int
    daily_demand_rate: Optional[float] = None
    expected_seven_day_demand: Optional[float] = None
    days_to_stockout: Optional[float] = None
    recommended_reorder_quantity: Optional[float] = None
    confidence_level: ConfidenceLevel
    forecast_tier: ForecastTier
    forecast_status: ForecastStatus
    is_reorder_provisional: bool = False
    assumptions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ShopForecastSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shop_id: UUID
    generated_at: str
    total_products_analyzed: int
    tier_1_count: int
    tier_2_count: int
    tier_3_count: int
    out_of_stock_count: int
    at_risk_stockout_7d_count: int
    forecasts: List[ProductDemandForecast]
