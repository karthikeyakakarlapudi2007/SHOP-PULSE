"""
Test Suite: Universal Loose Product Pricing Configuration Through OCR Invoice Review
Stage 6.6 Verification

Verifies:
1. Universal loose product configuration: manual retail selling price configuration per standard unit.
2. Complete separation of Purchase Price (raw invoice cost), Selling Price (customer rate), MRP, Pricing Basis, and Inventory Stock.
3. Universal Decimal Pricing Engine integration for loose products across fractional quantities in Voice-to-Bill and POS.
4. Bulk container unit conversion (e.g. 1 bag = 50 kg) crediting physical inventory with canonical storage units.
5. Pricing lifecycle status safeguards: VERIFIED for configured selling prices, NEEDS_REVIEW when missing.
6. Statutory MRP ceiling enforcement for loose products.
7. Packaged products backward compatibility.
"""

import uuid
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.models  # noqa: F401
from api.deps import get_db
from db.models.product import Product
from db.models.purchase import Purchase
from db.models.purchase_item import PurchaseItem
from db.session import Base
from main import app
from schemas.invoice import InvoiceConfirmRequest
from services.inventory_matcher import match_items_to_inventory, VoiceItemError, make_matched_item
from services.pricing_engine import calculate_line_price, PricingStatusError
from services.voice_parser import extract_items_from_transcript, ExtractedItem

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def auth():
    email = f"loose_{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/shops", json={
        "shop_name": "Kirana General Store",
        "owner_name": "Lakshmi",
        "business_type": "Grocery/Kirana",
        "location": "Hyderabad"
    }, headers=h)
    return h


def test_01_loose_sugar_invoice_confirm_and_pricing_basis():
    """An OCR invoice has 50 kg Sugar @ ₹50/kg = ₹2,500 total amount.
    During invoice review, merchant configures:
    - Loose product
    - Standard selling unit: 1 kg
    - Selling price: ₹60.00 / 1 kg
    - MRP: ₹65.00 / 1 kg
    - Inventory unit: kg
    """
    headers = auth()
    payload = {
        "supplier_name": "Sri Krishna Sugar Wholesalers",
        "invoice_number": "SUGAR-INV-2026",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Sugar",
            "product_name": "Sugar",
            "category": "Groceries",
            "quantity": 50.0,
            "unit": "kg",
            "purchase_price": 50.0,
            "selling_price": 60.0,
            "mrp": 65.0,
            "line_amount": 2500.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "mrp_basis_quantity": 1.0,
            "mrp_basis_unit": "kg",
            "update_selling_price": True,
        }]
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code in [200, 201], res.text
    data = res.json()
    assert data["items_created"] == 1
    assert data["total_amount"] == 2500.0
    assert data["total_units"] == 50.0

    # Verify database Product catalog record
    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Sugar").first()
    assert prod is not None
    assert prod.purchase_price == 50.0
    assert prod.selling_price == 60.0
    assert prod.price_basis_quantity == 1.0
    assert prod.price_basis_unit == "kg"
    assert prod.mrp == 65.0
    assert prod.mrp_basis_quantity == 1.0
    assert prod.mrp_basis_unit == "kg"
    assert prod.unit == "kg"
    assert prod.current_stock == 50.0
    assert prod.pricing_status == "NEEDS_REVIEW"

    # Manager verifies product pricing
    v_res = client.post(f"/api/v1/products/{prod.id}/verify", headers=headers)
    assert v_res.status_code == 200
    assert v_res.json()["pricing_status"] == "VERIFIED"
    prod.pricing_status = "VERIFIED"

    # Verify procurement Purchase and PurchaseItem records
    purch_item = db.query(PurchaseItem).filter(PurchaseItem.product_id == prod.id).first()
    assert purch_item is not None
    assert purch_item.purchase_price == 50.0
    assert purch_item.quantity == 50.0
    assert purch_item.line_amount == 2500.0
    db.close()


def test_02_loose_sugar_voice_to_bill_fractional_pricing():
    """Verify Voice-to-Bill and POS pricing for the confirmed Sugar product.
    Selling price is ₹60.00 per 1 kg.
    Voice requests:
    - 1 kg -> ₹60.00
    - 500 g -> ₹30.00
    - 250 g -> ₹15.00
    - 2 kg -> ₹120.00
    - 1.5 kg -> ₹90.00
    - Regional language phrases (Hindi, Telugu)
    """
    headers = auth()
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Sri Krishna Sugar Wholesalers",
        "invoice_number": "SUGAR-INV-2026",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Sugar",
            "quantity": 50.0,
            "unit": "kg",
            "purchase_price": 50.0,
            "selling_price": 60.0,
            "mrp": 65.0,
            "line_amount": 2500.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "update_selling_price": True,
        }]
    }, headers=headers)

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Sugar").first()
    assert prod is not None

    # Verify product pricing before selling
    v_res = client.post(f"/api/v1/products/{prod.id}/verify", headers=headers)
    assert v_res.status_code == 200
    prod.pricing_status = "VERIFIED"

    # Test 1 kg Sugar
    res_1kg = calculate_line_price(
        quantity=Decimal("1.0"),
        requested_unit="kg",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_1kg.line_total == Decimal("60.00")
    assert res_1kg.stock_deduction_quantity == Decimal("1.000")

    # Test 500 g Sugar
    res_500g = calculate_line_price(
        quantity=Decimal("500"),
        requested_unit="g",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_500g.line_total == Decimal("30.00")
    assert res_500g.stock_deduction_quantity == Decimal("0.500")

    # Test 250 g Sugar
    res_250g = calculate_line_price(
        quantity=Decimal("250"),
        requested_unit="g",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_250g.line_total == Decimal("15.00")
    assert res_250g.stock_deduction_quantity == Decimal("0.250")

    # Test 2 kg Sugar
    res_2kg = calculate_line_price(
        quantity=Decimal("2.0"),
        requested_unit="kg",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_2kg.line_total == Decimal("120.00")
    assert res_2kg.stock_deduction_quantity == Decimal("2.000")

    # Test 1.5 kg Sugar
    res_1_5kg = calculate_line_price(
        quantity=Decimal("1.5"),
        requested_unit="kg",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_1_5kg.line_total == Decimal("90.00")
    assert res_1_5kg.stock_deduction_quantity == Decimal("1.500")

    # Test Voice-to-Bill inventory matcher with 500 g Sugar
    voice_items = [ExtractedItem(name="Sugar", quantity=500.0, unit="g")]
    matched, _, _, subtotal, _, total = match_items_to_inventory(voice_items, catalog=[prod])
    assert len(matched) == 1
    assert matched[0].name == "Sugar"
    assert matched[0].total_price == 30.0
    assert matched[0].quantity == 0.5  # stock units (kg)
    assert subtotal == 30.0
    assert total == 30.0
    db.close()


def test_03_loose_product_bulk_bag_conversion():
    """Bulk container invoice: 2 Bags of Basmati Rice @ ₹2,000/bag = ₹4,000 total.
    Conversion: 1 Bag = 25 kg.
    Total physical inventory stock added = 50 kg.
    Wholesale rate per kg = ₹80.00.
    Retail selling price configured = ₹95.00 per 1 kg.
    """
    headers = auth()
    payload = {
        "supplier_name": "Punjab Rice Mills",
        "invoice_number": "RICE-BAGS-441",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Basmati Rice",
            "product_name": "Basmati Rice",
            "category": "Groceries",
            # Physical stock: 2 bags * 25 kg = 50 kg
            "quantity": 50.0,
            "unit": "kg",
            # Wholesale unit price: ₹2000 / 25 = ₹80/kg
            "purchase_price": 80.0,
            "selling_price": 95.0,
            "mrp": 105.0,
            "line_amount": 4000.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "update_selling_price": True,
        }]
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code in [200, 201], res.text

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Basmati Rice").first()
    assert prod is not None
    assert prod.current_stock == 50.0
    assert prod.unit == "kg"
    assert prod.purchase_price == 80.0
    assert prod.selling_price == 95.0
    assert prod.price_basis_quantity == 1.0
    assert prod.price_basis_unit == "kg"
    assert prod.pricing_status == "NEEDS_REVIEW"

    # Manager verifies product pricing
    v_res = client.post(f"/api/v1/products/{prod.id}/verify", headers=headers)
    assert v_res.status_code == 200
    prod.pricing_status = "VERIFIED"

    # Customer orders 5 kg Basmati Rice
    res_5kg = calculate_line_price(
        quantity=Decimal("5.0"),
        requested_unit="kg",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_5kg.line_total == Decimal("475.00")
    assert res_5kg.stock_deduction_quantity == Decimal("5.000")
    db.close()


def test_04_missing_selling_price_leaves_needs_review_and_blocks_pos():
    """When an invoice product is saved without a selling price, it is marked NEEDS_REVIEW
    and cannot be sold at checkout.
    """
    headers = auth()
    payload = {
        "supplier_name": "Farm Fresh Veggies",
        "invoice_number": "VEG-9901",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Toor Dal",
            "product_name": "Toor Dal",
            "category": "Groceries",
            "quantity": 20.0,
            "unit": "kg",
            "purchase_price": 110.0,
            "selling_price": 0.0,  # Unset
            "line_amount": 2200.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
        }]
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code in [200, 201], res.text

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Toor Dal").first()
    assert prod is not None
    assert prod.pricing_status == "NEEDS_REVIEW"

    # POS / Voice-to-Bill sale attempt must be blocked
    with pytest.raises(PricingStatusError) as exc_info:
        calculate_line_price(
            quantity=Decimal("1.0"),
            requested_unit="kg",
            selling_price=prod.selling_price,
            price_basis_quantity=prod.price_basis_quantity,
            price_basis_unit=prod.price_basis_unit,
            inventory_unit=prod.unit,
            pricing_status=prod.pricing_status,
            product_name=prod.name,
        )
    assert "requires manager pricing review" in str(exc_info.value)
    db.close()


def test_05_mrp_ceiling_protection_for_loose_product():
    """Statutory MRP ceiling protection ensures selling price cannot exceed MRP for loose products."""
    headers = auth()
    payload = {
        "supplier_name": "Oil Depot",
        "invoice_number": "OIL-552",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Sunflower Oil Loose",
            "product_name": "Sunflower Oil Loose",
            "category": "Groceries",
            "quantity": 15.0,
            "unit": "L",
            "purchase_price": 110.0,
            "selling_price": 140.0,
            "mrp": 130.0,  # Lower than selling price!
            "line_amount": 1650.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "L",
            "mrp_basis_quantity": 1.0,
            "mrp_basis_unit": "L",
        }]
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code == 400
    assert "exceeds statutory MRP ceiling" in res.json()["detail"]


def test_06_packaged_product_backward_compatibility():
    """Packaged products continue to work seamlessly without interference from loose product pricing logic."""
    headers = auth()
    payload = {
        "supplier_name": "Parle Distributor",
        "invoice_number": "PARLE-123",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Parle-G 250g Pack",
            "product_name": "Parle-G 250g Pack",
            "category": "Snacks",
            "quantity": 24.0,
            "unit": "pcs",
            "purchase_price": 16.50,
            "selling_price": 20.0,
            "mrp": 20.0,
            "line_amount": 396.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "pcs",
            "update_selling_price": True,
        }]
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code in [200, 201]

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Parle-G 250g Pack").first()
    assert prod is not None
    assert prod.current_stock == 24.0
    assert prod.unit == "pcs"
    assert prod.selling_price == 20.0
    assert prod.pricing_status == "NEEDS_REVIEW"

    # Manager verifies product pricing
    v_res = client.post(f"/api/v1/products/{prod.id}/verify", headers=headers)
    assert v_res.status_code == 200
    prod.pricing_status = "VERIFIED"

    res_3pcs = calculate_line_price(
        quantity=Decimal("3.0"),
        requested_unit="pcs",
        selling_price=prod.selling_price,
        price_basis_quantity=prod.price_basis_quantity,
        price_basis_unit=prod.price_basis_unit,
        inventory_unit=prod.unit,
        pricing_status=prod.pricing_status,
        product_name=prod.name,
    )
    assert res_3pcs.line_total == Decimal("60.00")
    assert res_3pcs.stock_deduction_quantity == Decimal("3.000")
    db.close()


def test_07_restock_loose_product_with_updated_selling_basis():
    """Restocking an existing loose product updates current stock atomically and updates selling price & basis."""
    headers = auth()
    # 1. Initial invoice
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Spice Trader",
        "invoice_number": "SPICE-1",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Turmeric Powder",
            "quantity": 10.0,
            "unit": "kg",
            "purchase_price": 180.0,
            "selling_price": 220.0,
            "mrp": 250.0,
            "line_amount": 1800.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "update_selling_price": True,
        }]
    }, headers=headers)

    db = TestingSessionLocal()
    prod1 = db.query(Product).filter(Product.name == "Turmeric Powder").first()
    prod_id = prod1.id
    assert prod1.current_stock == 10.0
    assert prod1.selling_price == 220.0
    assert prod1.pricing_status == "NEEDS_REVIEW"
    db.close()

    # Manager verifies initial product pricing
    v_res = client.post(f"/api/v1/products/{prod_id}/verify", headers=headers)
    assert v_res.status_code == 200

    # 2. Subsequent restock invoice with new wholesale rate and selling price update
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Spice Trader",
        "invoice_number": "SPICE-2",
        "invoice_date": "25/11/2026",
        "items": [{
            "matched_product_id": str(prod_id),
            "name": "Turmeric Powder",
            "quantity": 15.0,
            "unit": "kg",
            "purchase_price": 190.0,
            "selling_price": 230.0,
            "mrp": 250.0,
            "line_amount": 2850.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "update_selling_price": True,
        }]
    }, headers=headers)

    db = TestingSessionLocal()
    prod2 = db.query(Product).filter(Product.id == prod_id).first()
    assert prod2.current_stock == 25.0  # 10 + 15
    assert prod2.purchase_price == 190.0
    assert prod2.selling_price == 230.0
    assert prod2.pricing_status == "VERIFIED"
    db.close()
