import pytest
from uuid import UUID, uuid4
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from db.session import Base
from api.deps import get_db
from db.models.product import Product
from db.models.sale import Sale
from db.models.sale_item import SaleItem
from db.models.purchase import Purchase
from db.models.purchase_item import PurchaseItem

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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

client = TestClient(app)

def create_auth_shop(email_prefix: str = "inv_tester"):
    email = f"{email_prefix}_{uuid4().hex[:6]}@example.com"
    client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    login_res = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    shop_res = client.post("/api/v1/shops", json={
        "shop_name": "Test Kirana Store",
        "owner_name": "Kirana Owner",
        "business_type": "Grocery/Kirana"
    }, headers=headers)
    shop_id = UUID(shop_res.json()["id"])
    return headers, shop_id

# 1. Saving one extracted invoice item
def test_save_single_extracted_invoice_item():
    headers, _ = create_auth_shop("single_item")
    payload = {
        "supplier_name": "Shree Distributors",
        "invoice_number": "INV-1001",
        "invoice_date": "2026-11-11",
        "items": [
            {
                "name": "Tata Tea Gold 500g",
                "product_name": "Tata Tea Gold 500g",
                "category": "Beverages",
                "quantity": 10,
                "unit": "pack",
                "purchase_price": 280.0,
                "selling_price": 310.0,
                "mrp": 320.0,
            }
        ]
    }
    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["items_created"] == 1
    assert data["items_restocked"] == 0
    assert len(data["saved_products"]) == 1
    assert data["saved_products"][0]["name"] == "Tata Tea Gold 500g"
    assert data["saved_products"][0]["current_stock"] == 10
    assert data["saved_products"][0]["purchase_price"] == 280.0
    assert data["saved_products"][0]["selling_price"] == 310.0

# 2. Saving multiple extracted invoice items
def test_save_multiple_extracted_invoice_items():
    headers, _ = create_auth_shop("multi_items")
    payload = {
        "supplier_name": "Metro Cash & Carry",
        "invoice_number": "METRO-9988",
        "items": [
            {
                "product_name": "Aashirvaad Atta 10kg",
                "quantity": 15,
                "unit": "bag",
                "purchase_price": 420.0,
                "selling_price": 460.0,
                "mrp": 480.0
            },
            {
                "product_name": "Fortune Sunflower Oil 1L",
                "quantity": 24,
                "unit": "bottle",
                "purchase_price": 130.0,
                "selling_price": 145.0,
                "mrp": 155.0
            },
            {
                "product_name": "Maggi 2-Minute Noodles 70g",
                "quantity": 96,
                "unit": "pack",
                "purchase_price": 12.0,
                "selling_price": 14.0,
                "mrp": 14.0
            }
        ]
    }
    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["items_created"] == 3
    assert len(data["saved_products"]) == 3
    assert data["total_units"] == 135.0

# 3. Saving an item with missing required fields (validation failure)
def test_save_item_missing_required_fields_fails():
    headers, _ = create_auth_shop("missing_fields")
    # Empty name
    bad_payload1 = {
        "items": [{"name": "", "quantity": 10, "purchase_price": 50.0, "selling_price": 60.0}]
    }
    res1 = client.post("/api/v1/invoices/confirm", json=bad_payload1, headers=headers)
    assert res1.status_code == 422

    # Zero / negative quantity
    bad_payload2 = {
        "items": [{"name": "Item A", "quantity": 0, "purchase_price": 50.0, "selling_price": 60.0}]
    }
    res2 = client.post("/api/v1/invoices/confirm", json=bad_payload2, headers=headers)
    assert res2.status_code == 422

# 4. Saving an existing product without creating an unintended duplicate
def test_save_existing_product_restocks_without_duplicate():
    headers, _ = create_auth_shop("no_dups")
    # First create initial product
    p_init = client.post("/api/v1/products", json={
        "name": "Surf Excel Matic 2kg",
        "category": "Household",
        "selling_price": 380.0,
        "purchase_price": 330.0,
        "current_stock": 5
    }, headers=headers).json()

    # Now confirm an invoice containing that same product
    payload = {
        "supplier_name": "Hindustan Unilever",
        "invoice_number": "HUL-4455",
        "items": [
            {
                "product_name": "Surf Excel Matic 2kg",
                "quantity": 20,
                "purchase_price": 325.0,
                "selling_price": 385.0
            }
        ]
    }
    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["items_restocked"] == 1
    assert data["items_created"] == 0

    # Verify inventory count is still 1 product, but stock is 5 + 20 = 25
    prods = client.get("/api/v1/products", headers=headers).json()
    assert prods["total"] == 1
    assert prods["items"][0]["id"] == p_init["id"]
    assert prods["items"][0]["current_stock"] == 25
    assert prods["items"][0]["purchase_price"] == 325.0
    assert prods["items"][0]["selling_price"] == 385.0

# 5. Updating product information
def test_update_product_crud():
    headers, _ = create_auth_shop("update_test")
    p = client.post("/api/v1/products", json={
        "name": "Parle-G 250g",
        "selling_price": 20.0,
        "current_stock": 50
    }, headers=headers).json()
    pid = p["id"]

    update_res = client.put(f"/api/v1/products/{pid}", json={
        "selling_price": 25.0,
        "current_stock": 60,
        "category": "Snacks"
    }, headers=headers)
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["selling_price"] == 25.0
    assert updated["current_stock"] == 60
    assert updated["category"] == "Snacks"

# 6. Deleting an inventory item (without history -> hard delete)
def test_delete_inventory_item_no_history():
    headers, _ = create_auth_shop("del_clean")
    p = client.post("/api/v1/products", json={
        "name": "Temporary Test Item",
        "selling_price": 10.0,
        "current_stock": 1
    }, headers=headers).json()
    pid = p["id"]

    del_res = client.delete(f"/api/v1/products/{pid}", headers=headers)
    assert del_res.status_code == 204

    # Verify 404 on get
    get_res = client.get(f"/api/v1/products/{pid}", headers=headers)
    assert get_res.status_code == 404

    # Verify removed from list
    list_res = client.get("/api/v1/products", headers=headers).json()
    assert list_res["total"] == 0

# 7. Deleting a nonexistent product
def test_delete_nonexistent_product():
    headers, _ = create_auth_shop("del_404")
    fake_id = str(uuid4())
    res = client.delete(f"/api/v1/products/{fake_id}", headers=headers)
    assert res.status_code == 404

# 8. Deleting a product with related historical records (soft-delete / archive)
def test_delete_product_with_history_archives_safely():
    headers, shop_id = create_auth_shop("del_with_history")
    
    # Create product
    p = client.post("/api/v1/products", json={
        "name": "Heritage Milk 500ml",
        "selling_price": 30.0,
        "current_stock": 20
    }, headers=headers).json()
    pid = UUID(p["id"])

    # Record a sale referencing this product in the DB session directly
    db = TestingSessionLocal()
    sale = Sale(shop_id=shop_id, total_amount=30.0, payment_method="CASH")
    db.add(sale)
    db.flush()
    sale_item = SaleItem(sale_id=sale.id, product_id=pid, quantity=1, unit_price=30.0)
    db.add(sale_item)
    db.commit()
    db.close()

    # Now attempt to delete product via API
    del_res = client.delete(f"/api/v1/products/{pid}", headers=headers)
    assert del_res.status_code == 204

    # Verify active list excludes it
    list_res = client.get("/api/v1/products", headers=headers).json()
    assert list_res["total"] == 0
    assert not any(item["id"] == pid for item in list_res["items"])

    # Verify get by ID returns 404
    get_res = client.get(f"/api/v1/products/{pid}", headers=headers)
    assert get_res.status_code == 404

    # Verify historical financial record remains intact in database!
    db = TestingSessionLocal()
    db_sale_item = db.query(SaleItem).filter(SaleItem.product_id == pid).first()
    assert db_sale_item is not None
    assert db_sale_item.unit_price == 30.0

    db_prod = db.query(Product).filter(Product.id == pid).first()
    assert db_prod is not None
    assert db_prod.is_active is False
    db.close()

# 9. Saving without authentication fails
def test_saving_without_auth_fails():
    res = client.post("/api/v1/invoices/confirm", json={
        "items": [{"name": "No Auth", "quantity": 1, "purchase_price": 10.0}]
    })
    assert res.status_code == 401

# 10. Handling backend errors & atomic rollback
def test_confirm_atomic_rollback_on_failure():
    headers, shop_id = create_auth_shop("rollback_test")
    # Item 1 is valid, item 2 has no selling price for a brand-new product
    payload = {
        "items": [
            {"product_name": "Valid Item 1", "quantity": 5, "purchase_price": 100.0, "selling_price": 120.0},
            {"product_name": "Brand New Item 2", "quantity": 5, "purchase_price": 100.0, "selling_price": None}
        ]
    }
    res = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res.status_code == 400
    assert "Selling price is required" in res.json()["detail"]

    # Verify atomic rollback: neither item should exist in the shop
    prods = client.get("/api/v1/products", headers=headers).json()
    assert prods["total"] == 0

# 11 & 12. Refreshing inventory after saving & deleting
def test_inventory_list_reflects_changes_accurately():
    headers, _ = create_auth_shop("refresh_flow")
    # Save invoice item
    client.post("/api/v1/invoices/confirm", json={
        "items": [{"name": "Item A", "quantity": 10, "purchase_price": 50.0, "selling_price": 60.0}]
    }, headers=headers)

    # 11. Refresh / list
    res_list = client.get("/api/v1/products", headers=headers).json()
    assert res_list["total"] == 1
    assert res_list["items"][0]["name"] == "Item A"
    pid = res_list["items"][0]["id"]

    # 12. Delete and refresh
    client.delete(f"/api/v1/products/{pid}", headers=headers)
    res_list2 = client.get("/api/v1/products", headers=headers).json()
    assert res_list2["total"] == 0

# 13. Preventing duplicate submissions
def test_prevent_duplicate_invoice_confirmation():
    headers, _ = create_auth_shop("dup_submit")
    payload = {
        "supplier_name": "Unique Supplier Ltd",
        "invoice_number": "INV-DUP-777",
        "items": [{"name": "Item X", "quantity": 10, "purchase_price": 20.0, "selling_price": 25.0}]
    }
    res1 = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res1.status_code == 201

    # Second submission with same supplier & invoice number must raise 409 Conflict
    res2 = client.post("/api/v1/invoices/confirm", json=payload, headers=headers)
    assert res2.status_code == 409
    assert "already added to stock" in res2.json()["detail"]

# 14. Preserving inventory data across sessions
def test_inventory_persistence_across_queries():
    headers, shop_id = create_auth_shop("persistence_test")
    client.post("/api/v1/products", json={
        "name": "Dettol Soap 125g",
        "selling_price": 50.0,
        "purchase_price": 42.0,
        "current_stock": 30
    }, headers=headers)

    # Re-query directly via clean DB session
    db = TestingSessionLocal()
    p = db.query(Product).filter(Product.shop_id == shop_id, Product.name == "Dettol Soap 125g").first()
    assert p is not None
    assert p.current_stock == 30
    assert p.is_active is True
    db.close()
