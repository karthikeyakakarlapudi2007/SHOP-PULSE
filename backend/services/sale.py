from decimal import Decimal
from typing import Optional, List, Tuple
from uuid import UUID
from sqlalchemy.orm import Session

from db.models.sale import Sale
from db.models.sale_item import SaleItem
from db.models.product import Product
from schemas.sale import SaleCreate
from services.money import bill_total, to_number
from services.pricing_engine import calculate_line_price
from services.stock import format_quantity, remove_stock, InsufficientStockError

def create_sale(db: Session, sale_in: SaleCreate, shop_id: UUID) -> Sale:
    try:
        validated_items = []
        line_amounts = []

        # ---------------------------------------------------------------------
        # Phase 1: Pre-validation & Server-Authoritative Pricing Calculation
        # ---------------------------------------------------------------------
        for item in sale_in.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                raise ValueError(f"Product {item.product_id} not found.")
            if product.shop_id != shop_id:
                raise ValueError(f"Product '{product.name}' does not belong to your shop.")
            if not product.is_active:
                raise ValueError(f"Product '{product.name}' is inactive and cannot be sold.")

            # Resolve pricing basis and units from catalog
            req_unit = item.unit if item.unit and str(item.unit).strip() else product.unit
            basis_qty = product.price_basis_quantity if product.price_basis_quantity is not None else Decimal("1.0")
            basis_unit = product.price_basis_unit if product.price_basis_unit else product.unit
            status = product.pricing_status

            # Server-authoritative calculation via Pricing Engine (with statutory MRP ceiling check)
            pricing_result = calculate_line_price(
                quantity=item.quantity,
                requested_unit=req_unit,
                selling_price=product.selling_price,
                price_basis_quantity=basis_qty,
                price_basis_unit=basis_unit,
                inventory_unit=product.unit,
                product_conversions=None,
                client_unit_price=item.unit_price,
                pricing_status=status,
                product_name=product.name,
                mrp=product.mrp,
                mrp_basis_quantity=getattr(product, "mrp_basis_quantity", None),
                mrp_basis_unit=getattr(product, "mrp_basis_unit", None),
            )

            # Friendly pre-check of stock availability (atomic update enforces it during write)
            stock_qty_float = float(pricing_result.stock_deduction_quantity)
            if (product.current_stock or 0) < stock_qty_float:
                raise InsufficientStockError(
                    f"Insufficient stock for product '{product.name}'. "
                    f"Available: {format_quantity(product.current_stock)}, "
                    f"requested: {format_quantity(pricing_result.stock_deduction_quantity)}"
                )

            line_amounts.append(pricing_result.line_total)
            validated_items.append((product, pricing_result))

        # ---------------------------------------------------------------------
        # Phase 2: Create Sale Header
        # ---------------------------------------------------------------------
        total_amt = bill_total(line_amounts)
        db_sale = Sale(
            shop_id=shop_id,
            total_amount=to_number(total_amt),
            payment_method=sale_in.payment_method,
        )
        db.add(db_sale)
        db.flush()  # Obtain db_sale.id

        # ---------------------------------------------------------------------
        # Phase 3: Create Sale Items & Deduct Inventory Atomically
        # ---------------------------------------------------------------------
        for product, result in validated_items:
            db_item = SaleItem(
                sale_id=db_sale.id,
                product_id=product.id,
                quantity=float(result.stock_deduction_quantity),
                unit_price=to_number(result.effective_unit_price),
            )
            db.add(db_item)

            # Atomic conditional stock deduction:
            # UPDATE products SET current_stock = ROUND(current_stock - q, 3) WHERE id = :id AND current_stock >= q
            # Concurrent sales cannot oversell; rowcount != 1 raises InsufficientStockError
            remove_stock(db, product, result.stock_deduction_quantity)

        # ---------------------------------------------------------------------
        # Phase 4: Commit Entire Transaction Once
        # ---------------------------------------------------------------------
        db.commit()
        db.refresh(db_sale)

        # Trigger inventory alerts for products dropping below thresholds
        try:
            from datetime import datetime, timezone
            from db.models.shop import Shop
            from services.notification import create_notification
            from schemas.notification import NotificationCreate

            shop = db.query(Shop).filter(Shop.id == shop_id).first()
            if shop and shop.owner_id:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                for product, _ in validated_items:
                    reorder = product.reorder_level or 0
                    if product.current_stock <= 0:
                        create_notification(
                            db,
                            NotificationCreate(
                                user_id=shop.owner_id,
                                shop_id=shop_id,
                                title=f"Out of Stock: {product.name}",
                                message=f"{product.name} is out of stock (0 {product.unit or 'units'} remaining).",
                                category="inventory",
                                priority="critical",
                                product_id=product.id,
                                transaction_id=db_sale.id,
                                deep_link=f"/inventory?id={product.id}",
                                event_key=f"out_of_stock:{product.id}:{today_str}"
                            ),
                            cooldown_hours=12
                        )
                    elif product.reorder_level and product.current_stock <= reorder:
                        create_notification(
                            db,
                            NotificationCreate(
                                user_id=shop.owner_id,
                                shop_id=shop_id,
                                title=f"Low Stock Alert: {product.name}",
                                message=f"{product.name} dropped to {format_quantity(product.current_stock)} {product.unit or 'units'} (threshold: {format_quantity(reorder)} {product.unit or 'units'}).",
                                category="inventory",
                                priority="high",
                                product_id=product.id,
                                transaction_id=db_sale.id,
                                deep_link=f"/inventory?id={product.id}",
                                event_key=f"low_stock:{product.id}:{today_str}"
                            ),
                            cooldown_hours=12
                        )
        except Exception:
            pass

        return db_sale

    except Exception as e:
        db.rollback()
        raise e

def get_sale_by_id(db: Session, sale_id: UUID) -> Optional[Sale]:
    return db.query(Sale).filter(Sale.id == sale_id).first()

def get_sales_by_shop(
    db: Session,
    shop_id: UUID,
    skip: int = 0,
    limit: int = 10
) -> Tuple[List[Sale], int]:
    query = db.query(Sale).filter(Sale.shop_id == shop_id)
    total = query.count()
    items = query.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
    return items, total
