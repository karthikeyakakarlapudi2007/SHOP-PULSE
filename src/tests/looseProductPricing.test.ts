import { describe, it, expect } from 'vitest';
import { detectIsLooseProduct } from '../utils/looseProductPricing';
import { parseMultilingualVoiceBill } from '../utils/multilingualVoiceParser';
import type { Product } from '../types/product';

describe('Universal Loose Product Detection', () => {
  it('identifies common loose staples and measure units', () => {
    expect(detectIsLooseProduct('Sugar 50kg', 'kg')).toBe(true);
    expect(detectIsLooseProduct('Basmati Rice', 'kg')).toBe(true);
    expect(detectIsLooseProduct('Toor Dal', 'g')).toBe(true);
    expect(detectIsLooseProduct('Sunflower Oil', 'L')).toBe(true);
    expect(detectIsLooseProduct('Wheat Flour / Atta', 'kg')).toBe(true);
    expect(detectIsLooseProduct('Loose Potatoes', 'kg')).toBe(true);
    expect(detectIsLooseProduct('Turmeric Spices', 'g')).toBe(true);
  });

  it('keeps packaged discrete items as packaged by default', () => {
    expect(detectIsLooseProduct('Parle-G Gold Biscuits', 'pcs')).toBe(false);
    expect(detectIsLooseProduct('Lifebuoy Soap 100g Pack', 'pcs')).toBe(false);
    expect(detectIsLooseProduct('Dettol Antiseptic Bottle', 'bottle')).toBe(false);
    expect(detectIsLooseProduct('Notebook 200 Pages', 'pcs')).toBe(false);
  });
});

describe('Voice-to-Bill Fractional Pricing for Loose Products', () => {
  const looseSugar: Product = {
    id: 'sug-1',
    name: 'Sugar',
    category: 'Groceries',
    stock: 50,
    unit: 'kg',
    sellingPrice: 60,
    price: 60,
    purchasePrice: 50,
    mrp: 65,
    reorderLevel: 10,
    minStock: 10,
    status: 'In Stock',
    priceBasisQuantity: 1.0,
    priceBasisUnit: 'kg',
    pricingStatus: 'VERIFIED',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };

  it('calculates 1 kg sugar @ ₹60/kg correctly', () => {
    const res = parseMultilingualVoiceBill('1 kg sugar', [looseSugar], 'en-IN');
    expect(res.matched_items).toHaveLength(1);
    expect(res.matched_items[0].name).toBe('Sugar');
    expect(res.matched_items[0].quantity).toBe(1.0);
    expect(res.matched_items[0].total_price).toBe(60.0);
  });

  it('calculates 500 g sugar @ ₹60/kg correctly (half-kg = ₹30)', () => {
    const res = parseMultilingualVoiceBill('500 g sugar', [looseSugar], 'en-IN');
    expect(res.matched_items).toHaveLength(1);
    expect(res.matched_items[0].name).toBe('Sugar');
    expect(res.matched_items[0].quantity).toBe(0.5); // normalized to kg stock
    expect(res.matched_items[0].total_price).toBe(30.0);
  });

  it('calculates 250 g sugar @ ₹60/kg correctly (quarter-kg = ₹15)', () => {
    const res = parseMultilingualVoiceBill('250 g sugar', [looseSugar], 'en-IN');
    expect(res.matched_items).toHaveLength(1);
    expect(res.matched_items[0].name).toBe('Sugar');
    expect(res.matched_items[0].quantity).toBe(0.25);
    expect(res.matched_items[0].total_price).toBe(15.0);
  });

  it('calculates 2 kg sugar @ ₹60/kg correctly (= ₹120)', () => {
    const res = parseMultilingualVoiceBill('2 kg sugar', [looseSugar], 'en-IN');
    expect(res.matched_items).toHaveLength(1);
    expect(res.matched_items[0].quantity).toBe(2.0);
    expect(res.matched_items[0].total_price).toBe(120.0);
  });

  it('calculates Hindi "आधा किलो चीनी" (= 500 g = ₹30)', () => {
    const res = parseMultilingualVoiceBill('आधा किलो चीनी', [looseSugar], 'hi-IN');
    expect(res.matched_items).toHaveLength(1);
    expect(res.matched_items[0].name).toBe('Sugar');
    expect(res.matched_items[0].quantity).toBe(0.5);
    expect(res.matched_items[0].total_price).toBe(30.0);
  });

  it('calculates 1.5 kg sugar @ ₹60/kg correctly (= ₹90)', () => {
    const res = parseMultilingualVoiceBill('1.5 kg sugar', [looseSugar], 'en-IN');
    expect(res.matched_items).toHaveLength(1);
    expect(res.matched_items[0].quantity).toBe(1.5);
    expect(res.matched_items[0].total_price).toBe(90.0);
  });
});

describe('Manual POS and Cart Pricing for Universal Loose Products', () => {
  it('correctly calculates 250 g Spices @ ₹40 per 100 g (= ₹100.00)', async () => {
    const spices: Product = {
      id: 'spices-1',
      name: 'Black Pepper Spices',
      category: 'Spices',
      stock: 5000,
      unit: 'g',
      sellingPrice: 40,
      price: 40,
      purchasePrice: 25,
      mrp: 45,
      reorderLevel: 500,
      minStock: 500,
      status: 'In Stock',
      priceBasisQuantity: 100,
      priceBasisUnit: 'g',
      pricingStatus: 'VERIFIED',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    // Rate per 1 g should be ₹0.40
    const { catalogPrice, cartLineTotal } = await import('../utils/cartPricing');
    expect(catalogPrice(spices)).toBe(0.4);

    const line = { product: spices, quantity: 250 };
    expect(cartLineTotal(line)).toBe(100.0);
  });

  it('correctly calculates 500 ml and 750 ml Oil @ ₹150 per 1 L (= ₹75.00 and ₹112.50)', async () => {
    const oil: Product = {
      id: 'oil-1',
      name: 'Sunflower Oil',
      category: 'Groceries',
      stock: 50,
      unit: 'L',
      sellingPrice: 150,
      price: 150,
      purchasePrice: 120,
      mrp: 165,
      reorderLevel: 10,
      minStock: 10,
      status: 'In Stock',
      priceBasisQuantity: 1,
      priceBasisUnit: 'L',
      pricingStatus: 'VERIFIED',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    const { catalogPrice, cartLineTotal } = await import('../utils/cartPricing');
    expect(catalogPrice(oil)).toBe(150);

    expect(cartLineTotal({ product: oil, quantity: 0.5 })).toBe(75.0);
    expect(cartLineTotal({ product: oil, quantity: 0.75 })).toBe(112.5);
  });
});
