/**
 * @file looseProductPricing.ts
 * @description Helper utilities for detecting loose products and standardizing retail pricing configurations.
 */

const LOOSE_KEYWORDS = [
  'sugar', 'rice', 'dal', 'atta', 'wheat', 'oil', 'potato', 'onion', 'tomato',
  'pulse', 'flour', 'salt', 'chilli', 'mirchi', 'turmeric', 'haldi', 'jeera',
  'cumin', 'grain', 'spice', 'ginger', 'garlic', 'coriander', 'mustard', 'gram',
  'besan', 'maida', 'sooji', 'rava', 'paneer', 'ghee'
];

const LOOSE_MEASURES = new Set([
  'g', 'kg', 'gm', 'gram', 'grams', 'l', 'lt', 'ltr', 'liter', 'litre', 'ml', 'quintal'
]);

/**
 * Detect whether a product is likely sold as loose/bulk measure by weight/volume.
 */
export function detectIsLooseProduct(name: string, unit: string): boolean {
  const u = (unit || '').toLowerCase().trim();
  if (LOOSE_MEASURES.has(u)) return true;
  const n = (name || '').toLowerCase();
  return LOOSE_KEYWORDS.some((kw) => n.includes(kw));
}

/**
 * Resolve the standard reference selling unit (e.g. 'kg' or 'L').
 */
export function detectDefaultBasisUnit(unit: string, isLoose: boolean): string {
  const u = (unit || '').toLowerCase().trim();
  if (u.includes('l') || u === 'ml') return 'L';
  if (u.includes('g') || u === 'kg' || u === 'quintal') return 'kg';
  return isLoose ? 'kg' : (unit || 'pcs');
}
