from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict

class SalesOverviewResponse(BaseModel):
    total_sales: float
    transaction_count: int
    average_transaction_value: float
    previous_period_sales: float
    previous_period_transactions: int
    sales_growth_rate: Optional[float] = None
    period: str
    start_date: str
    end_date: str

    model_config = ConfigDict(from_attributes=True)


class ProductSalesPerformanceItem(BaseModel):
    product_id: UUID
    product_name: str
    category: Optional[str] = None
    quantity_sold: int
    revenue: float
    unit: Optional[str] = "pcs"
    previous_quantity_sold: Optional[int] = 0
    growth_rate: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ProductPerformanceResponse(BaseModel):
    best_selling: List[ProductSalesPerformanceItem]
    slow_moving: List[ProductSalesPerformanceItem]
    increasing_sales: List[ProductSalesPerformanceItem]
    declining_sales: List[ProductSalesPerformanceItem]


class SalesTrendPoint(BaseModel):
    date: str
    label: str
    revenue: float
    transaction_count: int


class SalesTrendsResponse(BaseModel):
    interval: str
    points: List[SalesTrendPoint]
    peak_day: Optional[str] = None
    peak_revenue: float = 0.0


class SalesInsightsResponse(BaseModel):
    overview: SalesOverviewResponse
    performance: ProductPerformanceResponse
    trends: SalesTrendsResponse
    has_sufficient_data: bool
    data_summary_note: Optional[str] = None


class InventoryStatusCounts(BaseModel):
    in_stock: int = 0
    low_stock: int = 0
    out_of_stock: int = 0
    overstocked: int = 0
    needs_attention: int = 0
    total_products: int = 0


class InventoryInsightItem(BaseModel):
    product_id: UUID
    product_name: str
    category: Optional[str] = None
    current_stock: int
    minimum_stock_threshold: int
    unit: Optional[str] = "pcs"
    status: str  # "IN STOCK", "LOW STOCK", "OUT OF STOCK", "OVERSTOCKED", "NEEDS ATTENTION"
    recommended_action: str
    urgency: str  # "critical", "high", "medium", "low"
    selling_price: float
    purchase_price: Optional[float] = None
    last_updated: Optional[str] = None
    is_threshold_configured: bool = False

    model_config = ConfigDict(from_attributes=True)


class InventoryInsightsResponse(BaseModel):
    counts: InventoryStatusCounts
    items: List[InventoryInsightItem]
    has_sufficient_data: bool


class AiInsightCard(BaseModel):
    id: str
    type: str  # "critical", "warning", "positive", "info"
    category: str  # "sales", "inventory", "action"
    title: str
    message: str
    metric: Optional[str] = None
    grounded_data_points: List[str] = []
    suggested_action: Optional[str] = None


class AiInsightsResponse(BaseModel):
    insights: List[AiInsightCard]
    overall_business_health: str
    has_sufficient_data: bool
    note: Optional[str] = None

