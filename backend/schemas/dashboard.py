from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from schemas.product import ProductResponse
from schemas.sale import SaleResponse
from schemas.quantity import Quantity

class TopProductResponse(ProductResponse):
    total_sold: Quantity = 0

class DashboardResponse(BaseModel):
    today_sales: float = 0.0
    products_count: int = 0
    low_stock_count: int = 0
    items_sold_today: Quantity = 0
    top_products: List[TopProductResponse] = []
    low_stock_products: List[ProductResponse] = []
    recent_sales: List[SaleResponse] = []

    model_config = ConfigDict(from_attributes=True)
