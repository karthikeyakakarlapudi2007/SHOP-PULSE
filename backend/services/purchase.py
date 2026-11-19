from decimal import Decimal
from typing import Optional, List, Tuple
from uuid import UUID
from sqlalchemy.orm import Session

from db.models.purchase import Purchase
from db.models.purchase_item import PurchaseItem
from db.models.product import Product
from db.models.supplier import Supplier
from schemas.purchase import PurchaseCreate
from services.money import keep_printed_precision, to_decimal, to_number
from services.stock import add_stock, to_stock_quantity

def create_purchase(db: Session, purchase_in: PurchaseCreate, shop_id: UUID) -> Purchase:
    try:
        # Validate supplier if provided
        if purchase_in.supplier_id:
            supplier = db.query(Supplier).filter(Supplier.id == purchase_in.supplier_id).first()
            if not supplier or supplier.shop_id != shop_id:
                raise ValueError("Supplier not found or does not belong to your shop.")

        # Validate products before mutating any stock
        products_to_update = []
        total_amount = Decimal("0")

        for item in purchase_in.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product or product.shop_id != shop_id:
                raise ValueError(f"Product {item.product_id} not found or does not belong to your shop.")
            
            # Quantity in the product's stock unit (fractions only for kg, g, L, ml; 250 g into kg -> 0.25)
            qty = to_stock_quantity(item.quantity, item.unit, product)
            # Decimal, no intermediate rounding; the price is per stock unit; totals keep up to 3 dp
            total_amount += qty * to_decimal(item.purchase_price)
            products_to_update.append((product, item, qty))

        # Create Purchase Header
        db_purchase = Purchase(
            shop_id=shop_id,
            supplier_id=purchase_in.supplier_id,
            total_amount=to_number(keep_printed_precision(total_amount)),
        )
        db.add(db_purchase)
        db.flush()  # Obtain db_purchase.id

        # Create Purchase Items & Update Inventory
        for product, item, qty in products_to_update:
            db_item = PurchaseItem(
                purchase_id=db_purchase.id,
                product_id=product.id,
                quantity=float(qty),
                purchase_price=item.purchase_price,
            )
            db.add(db_item)

            # Atomic stock increase in the same transaction; then the purchase price
            add_stock(db, product, qty)
            product.purchase_price = item.purchase_price
            db.add(product)

        db.commit()
        db.refresh(db_purchase)
        return db_purchase

    except Exception as e:
        db.rollback()
        raise e

def get_purchase_by_id(db: Session, purchase_id: UUID) -> Optional[Purchase]:
    return db.query(Purchase).filter(Purchase.id == purchase_id).first()

def get_purchases_by_shop(
    db: Session,
    shop_id: UUID,
    skip: int = 0,
    limit: int = 10
) -> Tuple[List[Purchase], int]:
    query = db.query(Purchase).filter(Purchase.shop_id == shop_id)
    total = query.count()
    items = query.order_by(Purchase.created_at.desc()).offset(skip).limit(limit).all()
    return items, total
