from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc, and_, or_

from db.models.sale import Sale
from db.models.sale_item import SaleItem
from db.models.product import Product
from services.money import quantize_half_up, round_currency, sale_line_amount, sum_decimal, to_decimal, to_number
from services.stock import quantity_number
from schemas.insights import (
    SalesOverviewResponse,
    ProductSalesPerformanceItem,
    ProductPerformanceResponse,
    SalesTrendPoint,
    SalesTrendsResponse,
    SalesInsightsResponse,
    InventoryStatusCounts,
    InventoryInsightItem,
    InventoryInsightsResponse,
    AiInsightCard,
    AiInsightsResponse,
)

def _parse_date_range(
    period: str,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None
) -> Tuple[datetime, datetime, datetime, datetime, str]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "today":
        current_start = today_start
        current_end = now
        duration = current_end - current_start
        prev_end = current_start
        prev_start = prev_end - timedelta(days=1)
        period_name = "today"
    elif period == "30d":
        current_end = now
        current_start = now - timedelta(days=30)
        prev_end = current_start
        prev_start = prev_end - timedelta(days=30)
        period_name = "last 30 days"
    elif period == "90d":
        current_end = now
        current_start = now - timedelta(days=90)
        prev_end = current_start
        prev_start = prev_end - timedelta(days=90)
        period_name = "last 90 days"
    elif period == "custom" and start_date_str and end_date_str:
        try:
            current_start = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            current_end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            duration = current_end - current_start
            prev_end = current_start
            prev_start = prev_end - duration
            period_name = "custom period"
        except Exception:
            current_end = now
            current_start = now - timedelta(days=7)
            prev_end = current_start
            prev_start = prev_end - timedelta(days=7)
            period_name = "last 7 days"
    else:  # default 7d
        current_end = now
        current_start = now - timedelta(days=7)
        prev_end = current_start
        prev_start = prev_end - timedelta(days=7)
        period_name = "last 7 days"

    return current_start, current_end, prev_start, prev_end, period_name


def get_sales_insights(
    db: Session,
    shop_id: UUID,
    period: str = "7d",
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None
) -> SalesInsightsResponse:
    c_start, c_end, p_start, p_end, period_label = _parse_date_range(period, start_date_str, end_date_str)
    
    # Naive fallback timestamps for SQLite compatibility
    c_start_naive = c_start.replace(tzinfo=None)
    c_end_naive = c_end.replace(tzinfo=None)
    p_start_naive = p_start.replace(tzinfo=None)
    p_end_naive = p_end.replace(tzinfo=None)

    # 1. Current Period Overview
    # Money is summed in Decimal from the stored bill totals (no binary SQL SUM); half-up to paise
    curr_totals = (
        db.query(Sale.total_amount)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                and_(Sale.created_at >= c_start, Sale.created_at <= c_end),
                and_(Sale.created_at >= c_start_naive, Sale.created_at <= c_end_naive)
            )
        )
        .all()
    )
    total_sales_d = round_currency(sum_decimal(t for (t,) in curr_totals))
    tx_count = len(curr_totals)
    avg_ticket_d = round_currency(total_sales_d / tx_count) if tx_count > 0 else Decimal("0")

    # 2. Previous Period Overview
    prev_totals = (
        db.query(Sale.total_amount)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                and_(Sale.created_at >= p_start, Sale.created_at < c_start),
                and_(Sale.created_at >= p_start_naive, Sale.created_at < c_start_naive)
            )
        )
        .all()
    )
    prev_total_d = round_currency(sum_decimal(t for (t,) in prev_totals))
    prev_tx_count = len(prev_totals)

    growth_rate: Optional[float] = None
    if prev_total_d > 0:
        growth_rate = to_number(quantize_half_up((total_sales_d - prev_total_d) / prev_total_d * 100, "0.1"))

    overview = SalesOverviewResponse(
        total_sales=to_number(total_sales_d),
        transaction_count=tx_count,
        average_transaction_value=to_number(avg_ticket_d),
        previous_period_sales=to_number(prev_total_d),
        previous_period_transactions=prev_tx_count,
        sales_growth_rate=growth_rate,
        period=period,
        start_date=c_start.isoformat(),
        end_date=c_end.isoformat(),
    )

    # 3. Product Performance in Current vs Previous Period
    curr_items_raw = (
        db.query(
            Product.id,
            Product.name,
            Product.category,
            Product.unit,
            func.sum(SaleItem.quantity).label("qty_sold"),
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                and_(Sale.created_at >= c_start, Sale.created_at <= c_end),
                and_(Sale.created_at >= c_start_naive, Sale.created_at <= c_end_naive)
            )
        )
        .group_by(Product.id)
        .all()
    )

    prev_items_raw = (
        db.query(
            Product.id,
            func.sum(SaleItem.quantity).label("prev_qty_sold")
        )
        .join(SaleItem, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                and_(Sale.created_at >= p_start, Sale.created_at < c_start),
                and_(Sale.created_at >= p_start_naive, Sale.created_at < c_start_naive)
            )
        )
        .group_by(Product.id)
        .all()
    )
    prev_qty_map: Dict[UUID, Any] = {r[0]: quantity_number(r[1]) for r in prev_items_raw}

    sold_products_list: List[ProductSalesPerformanceItem] = []
    active_sold_ids = set()

    # Revenue per product = sum of its sale lines, each rounded half-up to paise exactly as the bills are
    # (approved rule), computed in Decimal from the stored quantity and unit price of every line
    line_rows = (
        db.query(SaleItem.product_id, SaleItem.quantity, SaleItem.unit_price)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                and_(Sale.created_at >= c_start, Sale.created_at <= c_end),
                and_(Sale.created_at >= c_start_naive, Sale.created_at <= c_end_naive)
            )
        )
        .all()
    )
    revenue_by_product: Dict[Any, Decimal] = {}
    for line_pid, line_qty, line_price in line_rows:
        revenue_by_product[line_pid] = revenue_by_product.get(line_pid, Decimal("0")) + sale_line_amount(line_qty, line_price)

    for pid, pname, pcat, punit, qty in curr_items_raw:
        rev = revenue_by_product.get(pid, Decimal("0"))
        active_sold_ids.add(pid)
        prev_q = prev_qty_map.get(pid, 0)
        p_growth = None
        if prev_q > 0:
            p_growth = round(((qty - prev_q) / prev_q) * 100, 1)
        elif qty > 0 and prev_q == 0:
            p_growth = 100.0

        sold_products_list.append(
            ProductSalesPerformanceItem(
                product_id=pid,
                product_name=pname,
                category=pcat or "Other",
                quantity_sold=quantity_number(qty),
                revenue=to_number(rev),
                unit=punit or "pcs",
                previous_quantity_sold=prev_q,
                growth_rate=p_growth
            )
        )

    # Best-selling products (ranked by quantity sold desc, then revenue)
    best_selling = sorted(sold_products_list, key=lambda x: (x.quantity_sold, x.revenue), reverse=True)[:10]

    # Increasing & Declining sales
    increasing_sales = [p for p in sold_products_list if (p.growth_rate is not None and p.growth_rate > 0)]
    increasing_sales = sorted(increasing_sales, key=lambda x: x.growth_rate or 0, reverse=True)[:10]

    declining_sales = [p for p in sold_products_list if (p.growth_rate is not None and p.growth_rate < 0)]
    declining_sales = sorted(declining_sales, key=lambda x: x.growth_rate or 0)[:10]

    # Slow-moving products: active products with 0 or fewest sales in this period
    all_active_products = (
        db.query(Product)
        .filter(Product.shop_id == shop_id, Product.is_active == True)
        .all()
    )
    slow_moving: List[ProductSalesPerformanceItem] = []
    for prod in all_active_products:
        if prod.id not in active_sold_ids:
            slow_moving.append(
                ProductSalesPerformanceItem(
                    product_id=prod.id,
                    product_name=prod.name,
                    category=prod.category or "Other",
                    quantity_sold=0,
                    revenue=0.0,
                    unit=prod.unit or "pcs",
                    previous_quantity_sold=prev_qty_map.get(prod.id, 0),
                    growth_rate=-100.0 if prev_qty_map.get(prod.id, 0) > 0 else 0.0
                )
            )
    # Sort slow moving by current stock desc (excess capital tied up)
    slow_moving = sorted(slow_moving, key=lambda x: x.revenue)[:10]

    performance = ProductPerformanceResponse(
        best_selling=best_selling,
        slow_moving=slow_moving,
        increasing_sales=increasing_sales,
        declining_sales=declining_sales
    )

    # 4. Daily Sales Trends over the selected period
    # Bucket by date
    days_count = max((c_end.date() - c_start.date()).days + 1, 1)
    # Cap days points for charts (if > 90, group; otherwise daily)
    daily_points: List[SalesTrendPoint] = []
    peak_day: Optional[str] = None
    peak_rev = 0.0

    # Fetch all sales in current period with their dates
    sales_in_period = (
        db.query(Sale.created_at, Sale.total_amount)
        .filter(
            Sale.shop_id == shop_id,
            or_(
                and_(Sale.created_at >= c_start, Sale.created_at <= c_end),
                and_(Sale.created_at >= c_start_naive, Sale.created_at <= c_end_naive)
            )
        )
        .all()
    )

    date_agg: Dict[str, Dict[str, Any]] = {}
    for i in range(days_count):
        d = c_start.date() + timedelta(days=i)
        if d <= c_end.date():
            d_str = d.strftime("%Y-%m-%d")
            label = d.strftime("%d %b")
            date_agg[d_str] = {"label": label, "revenue": Decimal("0"), "count": 0}

    for dt, amt in sales_in_period:
        if dt:
            d_key = dt.strftime("%Y-%m-%d")
            if d_key in date_agg:
                date_agg[d_key]["revenue"] += to_decimal(amt) or Decimal("0")
                date_agg[d_key]["count"] += 1

    for d_str, data in sorted(date_agg.items()):
        rev = to_number(round_currency(data["revenue"]))
        cnt = data["count"]
        if rev > peak_rev:
            peak_rev = rev
            peak_day = data["label"]
        daily_points.append(
            SalesTrendPoint(
                date=d_str,
                label=data["label"],
                revenue=rev,
                transaction_count=cnt
            )
        )

    trends = SalesTrendsResponse(
        interval="daily" if days_count <= 31 else "weekly",
        points=daily_points,
        peak_day=peak_day,
        peak_revenue=peak_rev
    )

    has_data = tx_count > 0
    note = None if has_data else f"No transaction records found for {period_label}. Record sales to see live trends."

    return SalesInsightsResponse(
        overview=overview,
        performance=performance,
        trends=trends,
        has_sufficient_data=has_data,
        data_summary_note=note
    )


def get_inventory_insights(db: Session, shop_id: UUID) -> InventoryInsightsResponse:
    products = (
        db.query(Product)
        .filter(Product.shop_id == shop_id, Product.is_active == True)
        .all()
    )

    items: List[InventoryInsightItem] = []
    in_stock_cnt = 0
    low_stock_cnt = 0
    out_of_stock_cnt = 0
    overstocked_cnt = 0
    needs_attention_cnt = 0

    for p in products:
        stock = quantity_number(p.current_stock)  # fractional stock (2.5 kg) is never truncated
        reorder = quantity_number(p.reorder_level) if (p.reorder_level is not None) else 0
        has_threshold = p.reorder_level is not None and p.reorder_level > 0

        # Status & Action Classification
        if stock <= 0:
            status = "OUT OF STOCK"
            urgency = "critical"
            recommended_action = "Stock depleted; immediate supplier replenishment required."
            out_of_stock_cnt += 1
            needs_attention_cnt += 1
        elif has_threshold and stock <= reorder:
            status = "LOW STOCK"
            urgency = "high"
            deficit = quantity_number(max(to_decimal(reorder * 2) - to_decimal(stock), Decimal(5)))
            recommended_action = f"Stock is below minimum threshold ({reorder} {p.unit or 'units'}). Order at least {deficit} {p.unit or 'units'}."
            low_stock_cnt += 1
            needs_attention_cnt += 1
        elif has_threshold and stock >= (reorder * 5) and stock >= 40:
            status = "OVERSTOCKED"
            urgency = "low"
            recommended_action = "Stock level is more than 5x reorder threshold; evaluate sales velocity before reordering."
            overstocked_cnt += 1
        else:
            status = "IN STOCK"
            urgency = "low"
            recommended_action = "Stock level is healthy."
            in_stock_cnt += 1

        last_up = p.updated_at.isoformat() if p.updated_at else (p.created_at.isoformat() if p.created_at else None)

        items.append(
            InventoryInsightItem(
                product_id=p.id,
                product_name=p.name,
                category=p.category or "Other",
                current_stock=stock,
                minimum_stock_threshold=reorder,
                unit=p.unit or "pcs",
                status=status,
                recommended_action=recommended_action,
                urgency=urgency,
                selling_price=float(p.selling_price or 0.0),
                purchase_price=float(p.purchase_price) if p.purchase_price is not None else None,
                last_updated=last_up,
                is_threshold_configured=has_threshold
            )
        )

    # Sort items: critical (out of stock) first, then high (low stock), then overstocked, then in stock
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items = sorted(items, key=lambda x: (priority_order.get(x.urgency, 4), x.current_stock))

    counts = InventoryStatusCounts(
        in_stock=in_stock_cnt,
        low_stock=low_stock_cnt,
        out_of_stock=out_of_stock_cnt,
        overstocked=overstocked_cnt,
        needs_attention=needs_attention_cnt,
        total_products=len(products)
    )

    return InventoryInsightsResponse(
        counts=counts,
        items=items,
        has_sufficient_data=len(products) > 0
    )


def get_ai_insights(db: Session, shop_id: UUID) -> AiInsightsResponse:
    sales_data = get_sales_insights(db, shop_id, period="7d")
    inv_data = get_inventory_insights(db, shop_id)

    insights: List[AiInsightCard] = []

    # 1. Best seller explanation
    if sales_data.performance.best_selling:
        top_prod = sales_data.performance.best_selling[0]
        insights.append(
            AiInsightCard(
                id="ai-top-seller",
                type="positive",
                category="sales",
                title=f"Top Revenue Driver: {top_prod.product_name}",
                message=f"{top_prod.product_name} generated ₹{top_prod.revenue:,.2f} with {top_prod.quantity_sold} {top_prod.unit} sold over the last 7 days. Ensure adequate inventory to maintain this momentum.",
                metric=f"₹{top_prod.revenue:,.0f}",
                grounded_data_points=[
                    f"Product: {top_prod.product_name}",
                    f"Quantity sold: {top_prod.quantity_sold} {top_prod.unit}",
                    f"Revenue: ₹{top_prod.revenue:,.2f}"
                ],
                suggested_action="Verify supplier lead time and reorder schedule."
            )
        )

    # 2. Out of stock explanation
    out_of_stock_items = [it for it in inv_data.items if it.status == "OUT OF STOCK"]
    if out_of_stock_items:
        names = ", ".join([it.product_name for it in out_of_stock_items[:3]])
        remaining_cnt = len(out_of_stock_items) - 3
        suffix = f" and {remaining_cnt} more" if remaining_cnt > 0 else ""
        insights.append(
            AiInsightCard(
                id="ai-stockout-critical",
                type="critical",
                category="inventory",
                title=f"Critical Stockout: {len(out_of_stock_items)} items unavailable",
                message=f"Products currently depleted: {names}{suffix}. Stockouts directly lead to customer churn and missed revenue.",
                metric=f"{len(out_of_stock_items)} stockouts",
                grounded_data_points=[f"{it.product_name}: 0 {it.unit} remaining" for it in out_of_stock_items[:5]],
                suggested_action="Create supplier restock purchase order immediately."
            )
        )

    # 3. Low stock explanation
    low_stock_items = [it for it in inv_data.items if it.status == "LOW STOCK"]
    if low_stock_items:
        lead_item = low_stock_items[0]
        insights.append(
            AiInsightCard(
                id="ai-low-stock-warning",
                type="warning",
                category="inventory",
                title=f"Reorder Recommended: {lead_item.product_name}",
                message=f"{lead_item.product_name} has {lead_item.current_stock} {lead_item.unit} remaining, below the configured threshold of {lead_item.minimum_stock_threshold} {lead_item.unit}.",
                metric=f"{lead_item.current_stock} left",
                grounded_data_points=[
                    f"Product: {lead_item.product_name}",
                    f"Current Stock: {lead_item.current_stock}",
                    f"Minimum Threshold: {lead_item.minimum_stock_threshold}"
                ],
                suggested_action=lead_item.recommended_action
            )
        )

    # 4. Sales growth/decline explanation
    growth = sales_data.overview.sales_growth_rate
    if growth is not None:
        if growth >= 10.0:
            insights.append(
                AiInsightCard(
                    id="ai-sales-growth",
                    type="positive",
                    category="sales",
                    title="Healthy Revenue Acceleration",
                    message=f"Sales grew by +{growth}% compared to the prior 7-day period (₹{sales_data.overview.total_sales:,.2f} vs ₹{sales_data.overview.previous_period_sales:,.2f}).",
                    metric=f"+{growth}%",
                    grounded_data_points=[
                        f"Current 7-day sales: ₹{sales_data.overview.total_sales:,.2f}",
                        f"Previous 7-day sales: ₹{sales_data.overview.previous_period_sales:,.2f}",
                        f"Difference: +₹{round_currency(to_decimal(sales_data.overview.total_sales) - to_decimal(sales_data.overview.previous_period_sales)):,.2f}"
                    ],
                    suggested_action="Review top selling items to support customer demand."
                )
            )
        elif growth <= -10.0:
            insights.append(
                AiInsightCard(
                    id="ai-sales-decline",
                    type="warning",
                    category="sales",
                    title="Sales Contraction Detected",
                    message=f"Sales volume dropped by {growth}% compared to the prior 7-day period (₹{sales_data.overview.total_sales:,.2f} vs ₹{sales_data.overview.previous_period_sales:,.2f}).",
                    metric=f"{growth}%",
                    grounded_data_points=[
                        f"Current 7-day sales: ₹{sales_data.overview.total_sales:,.2f}",
                        f"Previous 7-day sales: ₹{sales_data.overview.previous_period_sales:,.2f}"
                    ],
                    suggested_action="Check whether key inventory items were stocked out during this period."
                )
            )

    # 5. Overstocked capital warning
    overstocked_items = [it for it in inv_data.items if it.status == "OVERSTOCKED"]
    if overstocked_items:
        lead_over = overstocked_items[0]
        insights.append(
            AiInsightCard(
                id="ai-overstock-info",
                type="info",
                category="inventory",
                title=f"Excess Inventory: {lead_over.product_name}",
                message=f"{lead_over.product_name} holds {lead_over.current_stock} {lead_over.unit} (threshold: {lead_over.minimum_stock_threshold} {lead_over.unit}). Consider bundling or promotional displays to accelerate turnover.",
                metric=f"{lead_over.current_stock} units",
                grounded_data_points=[
                    f"Product: {lead_over.product_name}",
                    f"Current Stock: {lead_over.current_stock}",
                    f"Threshold: {lead_over.minimum_stock_threshold}"
                ],
                suggested_action="Pause new purchase orders until inventory normalizes."
            )
        )

    # General Business Health Assessment
    if inv_data.counts.out_of_stock > 0 or (growth is not None and growth < -20):
        health = "Needs Attention"
    elif inv_data.counts.low_stock > 2:
        health = "Moderate Risk"
    else:
        health = "Healthy"

    has_data = len(insights) > 0 or sales_data.has_sufficient_data or inv_data.has_sufficient_data
    note = None if has_data else "Insufficient historical sales and inventory data to compute AI recommendations. Continue recording store activity."

    return AiInsightsResponse(
        insights=insights,
        overall_business_health=health,
        has_sufficient_data=has_data,
        note=note
    )

