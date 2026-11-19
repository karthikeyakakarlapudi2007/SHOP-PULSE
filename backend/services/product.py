from datetime import datetime, timezone
from typing import Optional, List, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.models.product import Product
from db.models.sale_item import SaleItem
from db.models.purchase_item import PurchaseItem
from schemas.product import ProductCreate, ProductUpdate
from services.stock import validate_stock_value, validate_unit_text


def _check_unit_and_stock(unit, current_stock, reorder_level) -> None:
    """A given unit must be registered; stock and reorder level must suit it (fractions only for kg, g, L, ml)."""
    if unit is not None:
        validate_unit_text(unit, what="Unit")
    if current_stock is not None:
        validate_stock_value(current_stock, unit, label="Stock")
    if reorder_level is not None:
        validate_stock_value(reorder_level, unit, label="Reorder level")


def create_product(db: Session, product_in: ProductCreate, shop_id: UUID) -> Product:
    _check_unit_and_stock(product_in.unit, product_in.current_stock, product_in.reorder_level)
    # If a previously deleted/archived product with the same name exists, reactivate it
    existing_inactive = db.query(Product).filter(
        Product.shop_id == shop_id,
        Product.name.ilike(product_in.name.strip()),
        Product.is_active.is_(False)
    ).first()

    if existing_inactive:
        existing_inactive.is_active = True
        existing_inactive.category = product_in.category or existing_inactive.category
        existing_inactive.selling_price = product_in.selling_price
        existing_inactive.purchase_price = product_in.purchase_price
        existing_inactive.current_stock = product_in.current_stock
        existing_inactive.reorder_level = product_in.reorder_level
        existing_inactive.unit = product_in.unit or existing_inactive.unit
        existing_inactive.sku = product_in.sku or existing_inactive.sku
        existing_inactive.supplier_id = product_in.supplier_id or existing_inactive.supplier_id
        if product_in.mrp is not None:
            existing_inactive.mrp = product_in.mrp
            existing_inactive.mrp_source = product_in.mrp_source or "MANUAL"
            existing_inactive.mrp_updated_at = datetime.now(timezone.utc)
        db.add(existing_inactive)
        db.commit()
        db.refresh(existing_inactive)
        return existing_inactive

    db_product = Product(
        name=product_in.name.strip(),
        category=product_in.category,
        selling_price=product_in.selling_price,
        purchase_price=product_in.purchase_price,
        mrp=product_in.mrp,
        mrp_source=(product_in.mrp_source or "MANUAL") if product_in.mrp is not None else None,
        mrp_updated_at=datetime.now(timezone.utc) if product_in.mrp is not None else None,
        current_stock=product_in.current_stock,
        reorder_level=product_in.reorder_level,
        unit=product_in.unit,
        supplier_id=product_in.supplier_id,
        sku=product_in.sku,
        shop_id=shop_id,
        is_active=True,
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def get_product_by_id(db: Session, product_id: UUID) -> Optional[Product]:
    return db.query(Product).filter(Product.id == product_id).first()

def get_products_by_shop(
    db: Session,
    shop_id: UUID,
    search: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
    include_inactive: bool = False
) -> Tuple[List[Product], int]:
    query = db.query(Product).filter(Product.shop_id == shop_id)
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))
    
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(Product.name.ilike(search_pattern))
        
    if category:
        query = query.filter(Product.category.ilike(category))
        
    total = query.count()
    items = query.order_by(Product.created_at.desc()).offset(skip).limit(limit).all()
    return items, total

def update_product(db: Session, db_product: Product, product_in: ProductUpdate) -> Product:
    update_data = product_in.model_dump(exclude_unset=True)
    if {"unit", "current_stock", "reorder_level"} & set(update_data):
        # Check the resulting unit, stock and reorder level together (a unit change must suit the stock)
        final_unit = update_data["unit"] if "unit" in update_data else db_product.unit
        if update_data.get("unit") is not None:
            validate_unit_text(update_data["unit"], what="Unit")
        stock = update_data.get("current_stock", db_product.current_stock)
        if stock is not None and ("current_stock" in update_data or "unit" in update_data):
            validate_stock_value(stock, final_unit, label="Stock")
        reorder = update_data.get("reorder_level", db_product.reorder_level)
        if reorder is not None and ("reorder_level" in update_data or "unit" in update_data):
            validate_stock_value(reorder, final_unit, label="Reorder level")
    mrp_source = update_data.pop("mrp_source", None)
    if "mrp" in update_data and update_data["mrp"] != db_product.mrp:
        # Track where the MRP came from whenever it changes
        db_product.mrp_source = (mrp_source or "MANUAL") if update_data["mrp"] is not None else None
        db_product.mrp_updated_at = datetime.now(timezone.utc)
    for field, value in update_data.items():
        setattr(db_product, field, value)
        
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

def delete_product(db: Session, db_product: Product) -> None:
    # Check if this product has historical financial records (sales or purchases)
    has_sales = db.query(SaleItem.id).filter(SaleItem.product_id == db_product.id).first() is not None
    has_purchases = db.query(PurchaseItem.id).filter(PurchaseItem.product_id == db_product.id).first() is not None

    if has_sales or has_purchases:
        # Soft delete / archive to preserve historical transaction records and avoid FK violation
        db_product.is_active = False
        db.add(db_product)
        db.commit()
    else:
        # Safe to hard-delete as no foreign references exist
        db.delete(db_product)
        db.commit()

def get_low_stock_products_by_shop(
    db: Session,
    shop_id: UUID,
    skip: int = 0,
    limit: int = 10
) -> Tuple[List[Product], int]:
    query = db.query(Product).filter(
        Product.shop_id == shop_id,
        Product.is_active.is_(True),
        Product.current_stock <= Product.reorder_level
    )
    total = query.count()
    items = query.order_by(Product.current_stock.asc()).offset(skip).limit(limit).all()
    return items, total
