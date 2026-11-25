"""
ShopPulse - Stage 6.7: Real-World Acceptance Testing Suite
Comprehensive End-to-End Acceptance Verification for Universal Loose Product Pricing.

Covers:
1. Production Database Safety & Isolation Verification
2. Invoice OCR Acceptance (Bulk packaging, loose classification, duplicate rejection, missing price validation)
3. Loose Product Pricing (Wholesale procurement vs retail catalog, NEEDS_REVIEW lifecycle, Cashier 403 vs Manager 200)
4. Multilingual Voice-to-Bill (English: 500g sugar = ₹30, Hindi: आधा किलो चीनी = ₹30, Telugu: పావు కిలో పంచదార = ₹15)
5. Manual POS Acceptance (Sugar 1kg/500g/250g, Spices ₹40/100g x 250g = ₹100, Oil ₹150/L x 500ml/750ml, Packaged)
6. Inventory & Stock Deductions (Stock addition, fractional deduction 75 - 1.75 = 73.25 kg, overselling prevention & rollback)
"""

import hashlib
import os
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
from db.models.sale import Sale
from db.models.sale_item import SaleItem
from db.models.shop_member import ShopMember, ShopRole
from db.models.user import User
from db.session import Base
from main import app
from services.pricing_engine import calculate_line_price, PricingStatusError
from services.voice_parser import extract_items_from_transcript
from services.inventory_matcher import match_items_to_inventory

# Strictly isolated in-memory test database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)

PROD_DB_PATH = "backend/shoppulse.db"
EXPECTED_PROD_HASH = "A9AC14FB33CF0EE875CFE71417D81C63C23D9125B76106F4CCEBF82B6A807815"
EXPECTED_PROD_SIZE = 401408


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def register_user(email: str, role: str = "owner"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!"})
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_shop_and_owner():
    email = f"owner_{uuid.uuid4().hex[:8]}@example.com"
    headers = register_user(email)
    shop_res = client.post("/api/v1/shops", json={
        "shop_name": "Sri Lakshmi Kirana Acceptance Store",
        "owner_name": "Lakshmi Narayana",
        "business_type": "Grocery/Kirana",
        "location": "Hyderabad"
    }, headers=headers)
    assert shop_res.status_code in [200, 201]
    shop_id = shop_res.json()["id"]
    return headers, shop_id


def create_cashier(shop_id: str, owner_headers: dict):
    cashier_email = f"cashier_{uuid.uuid4().hex[:8]}@example.com"
    cashier_headers = register_user(cashier_email)
    
    # Get cashier user id from db
    db = TestingSessionLocal()
    cashier_user = db.query(User).filter(User.email == cashier_email).first()
    assert cashier_user is not None
    cashier_id = cashier_user.id
    
    # Add as cashier to the shop
    member = ShopMember(
        shop_id=uuid.UUID(shop_id),
        user_id=cashier_id,
        role=ShopRole.CASHIER.value
    )
    db.add(member)
    db.commit()
    db.close()
    return cashier_headers


# =========================================================================
# SECTION 1: SAFETY REQUIREMENTS & DATABASE ISOLATION
# =========================================================================

def test_01_safety_production_database_integrity():
    """Verify that the production database file exists, is unmodified,
    matches exact SHA-256 and size baselines, and is not touched during tests."""
    assert os.path.exists(PROD_DB_PATH), "Production database file not found!"
    size = os.path.getsize(PROD_DB_PATH)
    with open(PROD_DB_PATH, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest().upper()
    
    assert size == EXPECTED_PROD_SIZE, f"Production DB size changed! Expected {EXPECTED_PROD_SIZE}, got {size}"
    assert sha256 == EXPECTED_PROD_HASH, f"Production DB SHA-256 altered! Expected {EXPECTED_PROD_HASH}, got {sha256}"


# =========================================================================
# SECTION 2: INVOICE OCR ACCEPTANCE & PRICING CONFIGURATION
# =========================================================================

def test_02_invoice_ocr_bulk_packaging_and_loose_configuration():
    """Verify end-to-end invoice confirmation with realistic bulk loose products:
    - Sugar 50 kg @ ₹50/kg = ₹2,500 total procurement cost.
    - Basmati Rice 2 Bags (25 kg/bag = 50 kg) @ ₹80/kg = ₹4,000 total.
    - Sunflower Oil 20 L @ ₹110/L = ₹2,200.
    - Turmeric Powder 5 kg @ ₹160/kg = ₹800.
    - Packaged Parle-G 24 pcs @ ₹16.50/pc = ₹396.
    """
    owner_headers, shop_id = create_shop_and_owner()
    
    payload = {
        "supplier_name": "Balaji Wholesale Traders",
        "invoice_number": "INV-BALAJI-2026-001",
        "invoice_date": "24/11/2026",
        "items": [
            {
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
            },
            {
                "name": "Basmati Rice",
                "product_name": "Basmati Rice",
                "category": "Groceries",
                "quantity": 50.0,  # 2 bags of 25 kg
                "unit": "kg",
                "purchase_price": 80.0,
                "selling_price": 95.0,
                "mrp": 105.0,
                "line_amount": 4000.0,
                "price_basis_quantity": 1.0,
                "price_basis_unit": "kg",
                "mrp_basis_quantity": 1.0,
                "mrp_basis_unit": "kg",
                "update_selling_price": True,
            },
            {
                "name": "Sunflower Oil",
                "product_name": "Sunflower Oil",
                "category": "Edible Oils",
                "quantity": 20.0,
                "unit": "L",
                "purchase_price": 110.0,
                "selling_price": 150.0,
                "mrp": 160.0,
                "line_amount": 2200.0,
                "price_basis_quantity": 1.0,
                "price_basis_unit": "L",
                "mrp_basis_quantity": 1.0,
                "mrp_basis_unit": "L",
                "update_selling_price": True,
            },
            {
                "name": "Turmeric Powder",
                "product_name": "Turmeric Powder",
                "category": "Spices",
                "quantity": 5.0,
                "unit": "kg",
                "purchase_price": 160.0,
                "selling_price": 40.0,
                "mrp": 45.0,
                "line_amount": 800.0,
                "price_basis_quantity": 100.0,  # ₹40 per 100g
                "price_basis_unit": "g",
                "mrp_basis_quantity": 100.0,
                "mrp_basis_unit": "g",
                "update_selling_price": True,
            },
            {
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
            }
        ]
    }

    res = client.post("/api/v1/invoices/confirm", json=payload, headers=owner_headers)
    assert res.status_code in [200, 201], res.text
    data = res.json()
    assert data["items_created"] == 5
    assert data["total_amount"] == 9896.0

    # Verify database separation of Wholesale Purchase vs Retail Catalog
    db = TestingSessionLocal()
    
    # 1. Procurement Purchase records retain original wholesale prices
    sugar_item = db.query(PurchaseItem).join(Product).filter(Product.name == "Sugar").first()
    assert sugar_item is not None
    assert sugar_item.purchase_price == 50.0
    assert sugar_item.quantity == 50.0
    assert sugar_item.line_amount == 2500.0

    # 2. Retail Product Catalog records retain configured selling price and basis
    sugar_prod = db.query(Product).filter(Product.name == "Sugar").first()
    assert sugar_prod.current_stock == 50.0
    assert sugar_prod.unit == "kg"
    assert sugar_prod.purchase_price == 50.0
    assert sugar_prod.selling_price == 60.0
    assert sugar_prod.price_basis_quantity == 1.0
    assert sugar_prod.price_basis_unit == "kg"
    assert sugar_prod.mrp == 65.0
    assert sugar_prod.pricing_status == "NEEDS_REVIEW"

    # Turmeric powder (spices) basis 100g
    turmeric_prod = db.query(Product).filter(Product.name == "Turmeric Powder").first()
    assert turmeric_prod.current_stock == 5.0
    assert turmeric_prod.unit == "kg"
    assert turmeric_prod.selling_price == 40.0
    assert turmeric_prod.price_basis_quantity == 100.0
    assert turmeric_prod.price_basis_unit == "g"
    assert turmeric_prod.pricing_status == "NEEDS_REVIEW"

    db.close()


def test_03_missing_selling_price_leaves_needs_review():
    """Verify that omitting retail selling price leaves product in NEEDS_REVIEW."""
    owner_headers, shop_id = create_shop_and_owner()
    payload = {
        "supplier_name": "Grain Mandi",
        "invoice_number": "INV-GRAIN-001",
        "invoice_date": "24/11/2026",
        "items": [{
            "name": "Chana Dal",
            "quantity": 30.0,
            "unit": "kg",
            "purchase_price": 75.0,
            "selling_price": 0.0,  # Unset
            "line_amount": 2250.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
        }]
    }
    res = client.post("/api/v1/invoices/confirm", json=payload, headers=owner_headers)
    assert res.status_code in [200, 201]

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Chana Dal").first()
    assert prod.pricing_status == "NEEDS_REVIEW"
    assert prod.selling_price == 0.0

    # Must be blocked at pricing engine
    with pytest.raises(PricingStatusError):
        calculate_line_price(
            quantity=Decimal("1.0"),
            requested_unit="kg",
            selling_price=prod.selling_price,
            price_basis_quantity=prod.price_basis_quantity,
            price_basis_unit=prod.price_basis_unit,
            inventory_unit=prod.unit,
            pricing_status=prod.pricing_status,
            product_name=prod.name
        )
    db.close()


def test_04_duplicate_invoice_protection():
    """Submitting the same invoice number for the same supplier must be rejected."""
    owner_headers, shop_id = create_shop_and_owner()
    payload = {
        "supplier_name": "Sri Krishna Sugar Wholesalers",
        "invoice_number": "SUGAR-BULK-2026",
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
    }

    # First attempt: succeeds
    res1 = client.post("/api/v1/invoices/confirm", json=payload, headers=owner_headers)
    assert res1.status_code in [200, 201]

    # Duplicate attempt: must be rejected with 409 Conflict
    res2 = client.post("/api/v1/invoices/confirm", json=payload, headers=owner_headers)
    assert res2.status_code == 409
    assert "already added to stock" in res2.json()["detail"]


# =========================================================================
# SECTION 3: ROLE-BASED ACCESS CONTROL FOR PRICING VERIFICATION
# =========================================================================

def test_05_rbac_cashier_cannot_verify_pricing():
    """Cashiers cannot bypass verification; only Owner/Manager can verify."""
    owner_headers, shop_id = create_shop_and_owner()
    cashier_headers = create_cashier(shop_id, owner_headers)

    # Ingest Sugar invoice
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Sri Krishna Sugar Wholesalers",
        "invoice_number": "SUGAR-INV-RBAC",
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
    }, headers=owner_headers)

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Sugar").first()
    assert prod.pricing_status == "NEEDS_REVIEW"
    prod_id = prod.id
    db.close()

    # Cashier attempts to verify: MUST be rejected with 403 Forbidden
    cashier_res = client.post(f"/api/v1/products/{prod_id}/verify", headers=cashier_headers)
    assert cashier_res.status_code == 403
    assert "Only Managers and Owners are authorized" in cashier_res.json()["detail"]

    # Owner attempts to verify: SUCCEEDS with 200 OK
    owner_res = client.post(f"/api/v1/products/{prod_id}/verify", headers=owner_headers)
    assert owner_res.status_code == 200
    assert owner_res.json()["pricing_status"] == "VERIFIED"


# =========================================================================
# SECTION 4: MULTILINGUAL VOICE-TO-BILL ACCEPTANCE
# =========================================================================

def test_06_voice_to_bill_multilingual_acceptance():
    """Verify Voice-to-Bill for loose sugar (@ ₹60/kg):
    1. English: '500g sugar' -> 0.5 kg @ ₹60/kg = ₹30.00
    2. Hindi: 'आधा किलो चीनी' -> 0.5 kg @ ₹60/kg = ₹30.00
    3. Telugu: 'పావు కిలో పంచదార' -> 0.25 kg @ ₹60/kg = ₹15.00
    Verifies that prices are computed on configured retail selling price, NOT bulk procurement.
    """
    owner_headers, shop_id = create_shop_and_owner()

    # Ingest and verify Sugar
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Sugar Mill",
        "invoice_number": "SUGAR-VOICE-001",
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
    }, headers=owner_headers)

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Sugar").first()
    # Verify pricing
    client.post(f"/api/v1/products/{prod.id}/verify", headers=owner_headers)
    prod.pricing_status = "VERIFIED"

    test_cases = [
        ("500g sugar", "en-IN", 0.5, 30.0),
        ("आधा किलो चीनी", "hi-IN", 0.5, 30.0),
        ("పావు కిలో పంచదార", "te-IN", 0.25, 15.0),
    ]

    for transcript, lang, expected_qty, expected_total in test_cases:
        # 1. Voice transcript parsing
        items = extract_items_from_transcript(transcript)
        assert len(items) == 1, f"Failed to extract item from '{transcript}'"
        assert items[0].quantity in [expected_qty, expected_qty * 1000]  # either 0.5 kg or 500 g

        # 2. Inventory matching and authoritative pricing
        matched, ambig, unmatched, subtotal, tax, total = match_items_to_inventory(items, catalog=[prod])
        assert len(matched) == 1, f"Failed to match '{transcript}': ambig={ambig}, unmatched={unmatched}"
        item = matched[0]
        assert item.name == "Sugar"
        assert item.quantity == expected_qty  # Canonical inventory stock unit (kg)
        assert item.total_price == expected_total  # Authoritative retail line price
        assert total == expected_total

        # 3. Via API endpoint /api/v1/voice/process
        req_payload = {
            "simulation_text": transcript,
            "language_code": lang,
        }
        api_res = client.post("/api/v1/voice/process", json=req_payload, headers=owner_headers)
        assert api_res.status_code == 200, api_res.text
        resp_data = api_res.json()
        assert len(resp_data["matched_items"]) == 1
        assert resp_data["matched_items"][0]["name"] == "Sugar"
        assert resp_data["matched_items"][0]["quantity"] == expected_qty
        assert resp_data["matched_items"][0]["total_price"] == expected_total
        assert resp_data["total"] == expected_total

    db.close()


# =========================================================================
# SECTION 5: MANUAL POS ACCEPTANCE ACROSS DIVERSE LOOSE PRODUCTS
# =========================================================================

def test_07_manual_pos_pricing_and_unit_conversions():
    """Verify manual POS checkout across diverse grocery categories:
    1. Sugar (@ ₹60/kg):
       - 1 kg -> ₹60.00
       - 500 g -> ₹30.00
       - 250 g -> ₹15.00
    2. Spices (@ ₹40 per 100g):
       - 250 g Turmeric -> ₹100.00
    3. Edible Oil (@ ₹150 per 1 L):
       - 500 ml -> ₹75.00
       - 750 ml -> ₹112.50
    4. Packaged Product:
       - Parle-G 3 pcs @ ₹20/pc -> ₹60.00
    """
    owner_headers, shop_id = create_shop_and_owner()

    # Ingest catalog
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Balaji Traders",
        "invoice_number": "INV-POS-ALL",
        "invoice_date": "24/11/2026",
        "items": [
            {
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
            },
            {
                "name": "Turmeric Powder",
                "quantity": 10.0,
                "unit": "kg",
                "purchase_price": 160.0,
                "selling_price": 40.0,
                "mrp": 45.0,
                "line_amount": 1600.0,
                "price_basis_quantity": 100.0,
                "price_basis_unit": "g",
                "update_selling_price": True,
            },
            {
                "name": "Sunflower Oil",
                "quantity": 25.0,
                "unit": "L",
                "purchase_price": 110.0,
                "selling_price": 150.0,
                "mrp": 160.0,
                "line_amount": 2750.0,
                "price_basis_quantity": 1.0,
                "price_basis_unit": "L",
                "update_selling_price": True,
            },
            {
                "name": "Parle-G 250g Pack",
                "quantity": 50.0,
                "unit": "pcs",
                "purchase_price": 16.50,
                "selling_price": 20.0,
                "mrp": 20.0,
                "line_amount": 825.0,
                "price_basis_quantity": 1.0,
                "price_basis_unit": "pcs",
                "update_selling_price": True,
            }
        ]
    }, headers=owner_headers)

    db = TestingSessionLocal()
    products = db.query(Product).all()
    for p in products:
        client.post(f"/api/v1/products/{p.id}/verify", headers=owner_headers)
        p.pricing_status = "VERIFIED"

    sugar = db.query(Product).filter(Product.name == "Sugar").first()
    turmeric = db.query(Product).filter(Product.name == "Turmeric Powder").first()
    oil = db.query(Product).filter(Product.name == "Sunflower Oil").first()
    parle = db.query(Product).filter(Product.name == "Parle-G 250g Pack").first()

    # 1. Sugar: 1 kg -> ₹60
    r_sugar_1k = calculate_line_price(
        quantity=Decimal("1.0"), requested_unit="kg", selling_price=sugar.selling_price,
        price_basis_quantity=sugar.price_basis_quantity, price_basis_unit=sugar.price_basis_unit,
        inventory_unit=sugar.unit, pricing_status="VERIFIED", product_name=sugar.name
    )
    assert r_sugar_1k.line_total == Decimal("60.00")
    assert r_sugar_1k.stock_deduction_quantity == Decimal("1.000")

    # Sugar: 500 g -> ₹30
    r_sugar_500g = calculate_line_price(
        quantity=Decimal("500"), requested_unit="g", selling_price=sugar.selling_price,
        price_basis_quantity=sugar.price_basis_quantity, price_basis_unit=sugar.price_basis_unit,
        inventory_unit=sugar.unit, pricing_status="VERIFIED", product_name=sugar.name
    )
    assert r_sugar_500g.line_total == Decimal("30.00")
    assert r_sugar_500g.stock_deduction_quantity == Decimal("0.500")

    # Sugar: 250 g -> ₹15
    r_sugar_250g = calculate_line_price(
        quantity=Decimal("250"), requested_unit="g", selling_price=sugar.selling_price,
        price_basis_quantity=sugar.price_basis_quantity, price_basis_unit=sugar.price_basis_unit,
        inventory_unit=sugar.unit, pricing_status="VERIFIED", product_name=sugar.name
    )
    assert r_sugar_250g.line_total == Decimal("15.00")
    assert r_sugar_250g.stock_deduction_quantity == Decimal("0.250")

    # 2. Spices: 250 g Turmeric @ ₹40/100g -> ₹100.00
    r_turmeric = calculate_line_price(
        quantity=Decimal("250"), requested_unit="g", selling_price=turmeric.selling_price,
        price_basis_quantity=turmeric.price_basis_quantity, price_basis_unit=turmeric.price_basis_unit,
        inventory_unit=turmeric.unit, pricing_status="VERIFIED", product_name=turmeric.name
    )
    assert r_turmeric.line_total == Decimal("100.00")
    assert r_turmeric.stock_deduction_quantity == Decimal("0.250")  # 0.250 kg deducted

    # 3. Oil: 500 ml @ ₹150/L -> ₹75.00
    r_oil_500 = calculate_line_price(
        quantity=Decimal("500"), requested_unit="ml", selling_price=oil.selling_price,
        price_basis_quantity=oil.price_basis_quantity, price_basis_unit=oil.price_basis_unit,
        inventory_unit=oil.unit, pricing_status="VERIFIED", product_name=oil.name
    )
    assert r_oil_500.line_total == Decimal("75.00")
    assert r_oil_500.stock_deduction_quantity == Decimal("0.500")

    # Oil: 750 ml @ ₹150/L -> ₹112.50
    r_oil_750 = calculate_line_price(
        quantity=Decimal("750"), requested_unit="ml", selling_price=oil.selling_price,
        price_basis_quantity=oil.price_basis_quantity, price_basis_unit=oil.price_basis_unit,
        inventory_unit=oil.unit, pricing_status="VERIFIED", product_name=oil.name
    )
    assert r_oil_750.line_total == Decimal("112.50")
    assert r_oil_750.stock_deduction_quantity == Decimal("0.750")

    # 4. Packaged: 3 pcs @ ₹20/pc -> ₹60.00
    r_parle = calculate_line_price(
        quantity=Decimal("3.0"), requested_unit="pcs", selling_price=parle.selling_price,
        price_basis_quantity=parle.price_basis_quantity, price_basis_unit=parle.price_basis_unit,
        inventory_unit=parle.unit, pricing_status="VERIFIED", product_name=parle.name
    )
    assert r_parle.line_total == Decimal("60.00")
    assert r_parle.stock_deduction_quantity == Decimal("3.000")

    db.close()


# =========================================================================
# SECTION 6: INVENTORY DEDUCTIONS, OVERSELLING & TRANSACTION ROLLBACK
# =========================================================================

def test_08_inventory_deduction_fractional_stock_and_rollback():
    """Test full inventory lifecycle:
    1. Initial Stock: 50 kg + 25 kg restock = 75 kg.
    2. Multi-item checkout: 1 kg + 500 g + 250 g = 1.75 kg.
    3. Final stock verified: exactly 73.250 kg.
    4. Overselling Prevention: Attempting to sell 100 kg is rejected with HTTP 400.
    5. Transaction Rollback: Failed overselling does not modify stock.
    """
    owner_headers, shop_id = create_shop_and_owner()

    # Invoice 1: 50 kg Sugar
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Sugar Supplier",
        "invoice_number": "SUGAR-LOT-1",
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
    }, headers=owner_headers)

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.name == "Sugar").first()
    prod_id = prod.id
    client.post(f"/api/v1/products/{prod_id}/verify", headers=owner_headers)
    db.close()

    # Invoice 2 (Restock): 25 kg Sugar
    client.post("/api/v1/invoices/confirm", json={
        "supplier_name": "Sugar Supplier",
        "invoice_number": "SUGAR-LOT-2",
        "invoice_date": "25/11/2026",
        "items": [{
            "matched_product_id": str(prod_id),
            "name": "Sugar",
            "quantity": 25.0,
            "unit": "kg",
            "purchase_price": 52.0,
            "selling_price": 60.0,
            "mrp": 65.0,
            "line_amount": 1300.0,
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
            "update_selling_price": True,
        }]
    }, headers=owner_headers)

    db = TestingSessionLocal()
    prod = db.query(Product).filter(Product.id == prod_id).first()
    assert prod.current_stock == 75.0  # 50 + 25 = 75 kg
    db.close()

    # Sale 1: 1 kg Sugar (₹60) + 500 g Sugar (₹30) + 250 g Sugar (₹15) = 1.75 kg total (₹105)
    sale_payload = {
        "payment_method": "cash",
        "customer_name": "Ramesh",
        "items": [
            {"product_id": str(prod_id), "quantity": 1.0, "unit": "kg"},
            {"product_id": str(prod_id), "quantity": 500.0, "unit": "g"},
            {"product_id": str(prod_id), "quantity": 250.0, "unit": "g"},
        ]
    }
    sale_res = client.post("/api/v1/sales", json=sale_payload, headers=owner_headers)
    assert sale_res.status_code == 201, sale_res.text
    sale_data = sale_res.json()
    assert sale_data["total_amount"] == 105.0

    # Verify inventory stock deduction
    db = TestingSessionLocal()
    prod_after_sale = db.query(Product).filter(Product.id == prod_id).first()
    # 75.0 - 1.75 = 73.250
    assert abs(prod_after_sale.current_stock - 73.250) < 0.0001
    db.close()

    # Overselling Prevention: Attempt to sell 100 kg Sugar (only 73.25 kg available)
    oversell_payload = {
        "payment_method": "cash",
        "items": [
            {"product_id": str(prod_id), "quantity": 100.0, "unit": "kg"}
        ]
    }
    oversell_res = client.post("/api/v1/sales", json=oversell_payload, headers=owner_headers)
    assert oversell_res.status_code == 400
    assert "Insufficient stock" in oversell_res.json()["detail"]

    # Verify transaction rollback: stock remains untouched at 73.25 kg
    db = TestingSessionLocal()
    prod_after_fail = db.query(Product).filter(Product.id == prod_id).first()
    assert abs(prod_after_fail.current_stock - 73.250) < 0.0001
    db.close()


# =========================================================================
# SECTION 7: REAL DIGITAL PDF INVOICE OCR ACCEPTANCE
# =========================================================================

def test_09_real_pdf_invoice_ocr_extraction():
    """Verify real invoice document extraction on genuine digital PDF fixture:
    File: TC01_clean_digital.pdf
    Expected:
    - Supplier: SRI BALAJI WHOLESALE TRADERS
    - Invoice Number: SBW-4101
    - Total Amount: ₹3,856.00
    - Items: Aashirvaad Atta 5kg, Tata Salt 1kg, Fortune Sunflower Oil 1L, Parle-G, Maggi
    - Grocery items classified correctly as is_grocery=True
    """
    from pathlib import Path
    from services.grocery_ocr.pipeline.invoice_pipeline import InvoicePipeline
    from services.grocery_ocr.config import default_config

    pdf_path = Path("backend/tests/fixtures/ground_truth/invoices/TC01_clean_digital.pdf")
    assert pdf_path.exists(), "TC01 PDF fixture missing"

    pipeline = InvoicePipeline(config=default_config)
    res = pipeline.process(pdf_path.read_bytes(), filename=pdf_path.name)

    assert "SBW-4101" in res.invoice_number
    assert "SRI BALAJI WHOLESALE TRADERS" in res.supplier_name
    assert res.calculated_total == Decimal("3856.00")
    assert len(res.items) == 5

    names = [it.raw_product_name for it in res.items]
    assert any("Aashirvaad Atta" in n for n in names)
    assert any("Tata Salt" in n for n in names)
    assert any("Sunflower Oil" in n for n in names)
    assert any("Parle-G" in n for n in names)
    assert any("Maggi" in n for n in names)

    for item in res.items:
        assert item.is_grocery is True
        assert item.purchase_price > 0
        assert item.quantity > 0
        assert item.calculated_amount > 0

