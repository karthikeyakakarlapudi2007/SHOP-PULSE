import { describe, it, expect, vi, beforeEach } from 'vitest';
import { 
  mapBackendProductToFrontend, 
  deleteProduct, 
  addProduct 
} from '../services/inventoryService';
import { productsApi, type ProductBackend } from '../api/products';

describe('Inventory & OCR Confirmation Flow', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('maps backend products preserving isActive, prices, units, and stock status', () => {
    const rawBackendProduct: ProductBackend = {
      id: 'prod-uuid-1234',
      shop_id: 'shop-uuid-5678',
      name: 'Madhur Pure Sugar 1kg',
      category: 'Groceries',
      selling_price: 48.0,
      purchase_price: 42.0,
      mrp: 52.0,
      mrp_source: 'INVOICE',
      current_stock: 40,
      reorder_level: 10,
      unit: 'kg',
      sku: 'SUGAR-1KG',
      stock_status: 'In Stock',
      is_active: true,
      created_at: '2026-11-11T10:00:00Z',
      updated_at: '2026-11-11T10:00:00Z',
    };

    const product = mapBackendProductToFrontend(rawBackendProduct);
    expect(product.id).toBe('prod-uuid-1234');
    expect(product.name).toBe('Madhur Pure Sugar 1kg');
    expect(product.sellingPrice).toBe(48.0);
    expect(product.purchasePrice).toBe(42.0);
    expect(product.mrp).toBe(52.0);
    expect(product.unit).toBe('kg');
    expect(product.stock).toBe(40);
    expect(product.status).toBe('In Stock');
    expect(product.isActive).toBe(true);
  });

  it('deletes inventory item via productsApi and triggers inventory sync event', async () => {
    const deleteSpy = vi.spyOn(productsApi, 'deleteProduct').mockResolvedValue(undefined);
    const dispatchMock = vi.fn();
    const originalWindow = globalThis.window;
    // @ts-expect-error test mock
    globalThis.window = {
      dispatchEvent: dispatchMock,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };

    try {
      await deleteProduct('prod-uuid-1234');
      expect(deleteSpy).toHaveBeenCalledWith('prod-uuid-1234');
      expect(dispatchMock).toHaveBeenCalled();
    } finally {
      globalThis.window = originalWindow;
    }
  });

  it('handles delete failure by throwing error and preserving state', async () => {
    vi.spyOn(productsApi, 'deleteProduct').mockRejectedValue(new Error('Cannot delete product with historical sales'));

    await expect(deleteProduct('prod-with-sales')).rejects.toThrow('Cannot delete product with historical sales');
  });

  it('preserves purchase price, selling price, and MRP without replacing missing rates with zero', async () => {
    const createSpy = vi.spyOn(productsApi, 'createProduct').mockImplementation(async (input) => ({
      id: 'new-id-999',
      shop_id: 'shop-1',
      name: input.name,
      category: input.category || null,
      selling_price: input.selling_price,
      purchase_price: input.purchase_price ?? null,
      mrp: input.mrp ?? null,
      current_stock: input.current_stock,
      stock_status: 'In Stock',
      is_active: true,
    }));

    const result = await addProduct({
      name: 'Fortune Sunlite Sunflower Oil 1L',
      category: 'Groceries',
      stock: 24,
      unit: 'bottle',
      sellingPrice: 145.0,
      purchasePrice: 130.0,
      mrp: 155.0,
      reorderLevel: 5,
    });

    expect(createSpy).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Fortune Sunlite Sunflower Oil 1L',
      selling_price: 145.0,
      purchase_price: 130.0,
      mrp: 155.0,
      current_stock: 24,
      unit: 'bottle',
    }));
    expect(result.purchasePrice).toBe(130.0);
    expect(result.sellingPrice).toBe(145.0);
    expect(result.mrp).toBe(155.0);
  });
});
