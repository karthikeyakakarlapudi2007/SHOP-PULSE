/**
 * Phase 3A review-screen behaviour: calculated values are labelled, free items are kept,
 * tax / discount parts are shown separately and direct photo uploads get quality warnings (R10).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  calculatedFieldLabels,
  componentSummary,
  formatMoney,
  fractionalQuantityNotice,
  hasFractionalQuantity,
  hasFreeUnits,
  isCalculated,
  isPhotoFile,
  photoWarning,
  promoBreakdown,
  promoPayload,
  reconciliationNotice,
  round3,
} from '../utils/invoiceReliability';
import { formatCurrency, formatPrintedCurrency } from '../utils/formatCurrency';
import type { PhotoAssessment } from '../api/documentPrep';

const assessment = (over: Partial<PhotoAssessment> = {}): PhotoAssessment => ({
  quality: {
    grade: 'GOOD',
    score: 90,
    retake_recommended: false,
    summary: 'Good photo. Only small corrections are needed.',
    metrics: {},
    issues: [{ code: 'skew', severity: 1, message: 'The page is tilted by 1.2 degrees.', correctable: true }],
  },
  retake_recommended: false,
  document: { found: true, outline_reliable: true, cut_off: false, cut_off_edges: [], reasons: [] },
  ...over,
});

describe('direct-upload photo warnings (R10)', () => {
  it('checks photos, not PDFs or text files', () => {
    expect(isPhotoFile({ name: 'bill.jpg', type: 'image/jpeg' })).toBe(true);
    expect(isPhotoFile({ name: 'IMG_0001.HEIC', type: '' })).toBe(true);
    expect(isPhotoFile({ name: 'scan.pdf', type: 'application/pdf' })).toBe(false);
    expect(isPhotoFile({ name: 'bill.txt', type: 'text/plain' })).toBe(false);
  });

  it('shows nothing for a good photo', () => {
    expect(photoWarning(assessment())).toBeNull();
    expect(photoWarning(null)).toBeNull();
  });

  it('asks for a retake for a poor or cut-off photo', () => {
    const w = photoWarning(
      assessment({
        retake_recommended: true,
        quality: {
          grade: 'POOR',
          score: 34,
          retake_recommended: true,
          summary: 'Poor photo.',
          metrics: {},
          issues: [
            { code: 'blur', severity: 3, message: 'The photo is blurry.', correctable: false },
            { code: 'skew', severity: 1, message: 'Tilted.', correctable: true },
            { code: 'contrast', severity: 2, message: 'The print is faint; contrast will be increased.', correctable: true },
          ],
        },
        document: { found: true, outline_reliable: false, cut_off: true, cut_off_edges: ['right'], reasons: [] },
      }),
    );
    expect(w?.retake).toBe(true);
    expect(w?.messages).toContain('The photo is blurry.');
    expect(w?.messages[0]).toMatch(/outside the photo/);
    expect(w?.messages).not.toContain('Tilted.');
    expect(w?.messages.some((m) => /contrast will be increased/.test(m))).toBe(false);
  });
});

describe('calculated values and invoice parts (R1, R6)', () => {
  it('labels calculated fields', () => {
    const item = { derived_fields: ['quantity', 'purchase_price'] };
    expect(calculatedFieldLabels(item)).toEqual(['quantity', 'rate']);
    expect(isCalculated(item, 'quantity')).toBe(true);
    expect(isCalculated({ derived_fields: [] }, 'quantity')).toBe(false);
  });

  it('summarises taxable, CGST, SGST and discounts separately, keeping a 3rd decimal', () => {
    expect(componentSummary({ taxable_amount: 363.6, cgst_amount: 9.09, sgst_amount: 9.09, scheme_discount: 14.4, other_discount: 0 }))
      .toBe('Taxable ₹363.60 · CGST ₹9.09 · SGST/UTGST ₹9.09 · Scheme disc ₹14.40');
    expect(componentSummary({ taxable_amount: 62.988 })).toBe('Taxable ₹62.988');
    expect(componentSummary({})).toBe('');
  });
});

describe('review screen source', () => {
  const src = readFileSync(resolve(__dirname, '../pages/InvoiceScanner.tsx'), 'utf-8');
  it('keeps a printed free item with a zero rate at confirmation', () => {
    expect(src).toMatch(/i\.is_free_item\) && i\.purchase_price === 0/);
  });
  it('runs the photo check for direct uploads', () => {
    expect(src).toMatch(/documentPrepApi\.assess\(file, file\.name\)/);
    expect(src).toMatch(/data-testid="direct-photo-warning"/);
  });
});


describe('three-decimal precision', () => {
  it('shows a printed third decimal and keeps two otherwise', () => {
    expect(formatMoney(62.988)).toBe('₹62.988');
    expect(formatMoney(440)).toBe('₹440.00');
    expect(formatMoney(4015.8)).toBe('₹4,015.80');
    expect(formatMoney(null)).toBe('—');
  });
  it('rounds calculated amounts to 3 decimals, never to paise', () => {
    expect(round3(12 * 7.143)).toBe(85.716);
    expect(round3(0.1 + 0.2)).toBe(0.3);
  });
  it('purchase documents keep the printed precision; the shared formatter is unchanged', () => {
    expect(formatPrintedCurrency(62.988)).toBe('₹62.988');
    expect(formatPrintedCurrency(2760)).toBe('₹2,760.00');
    expect(formatCurrency(62.988)).toBe('₹62.99');
  });
});

describe('paid + free units', () => {
  const promo = { quantity: 11, paid_quantity: 10, free_quantity: 1 };
  it('describes and sends the breakdown', () => {
    expect(hasFreeUnits(promo)).toBe(true);
    expect(promoBreakdown(promo)).toBe('10 paid + 1 free = 11 received');
    expect(promoPayload(promo)).toEqual({ paid_quantity: 10, free_quantity: 1 });
  });
  it('a printed free line is all free units', () => {
    const free = { quantity: 6, is_free_item: true, free_quantity: 6, paid_quantity: 0 };
    expect(hasFreeUnits(free)).toBe(true);
    expect(promoBreakdown(free)).toBe('6 free (printed rate ₹0.00)');
    expect(promoPayload(free)).toEqual({ is_free_item: true, paid_quantity: 0, free_quantity: 6 });
  });
  it('drops a breakdown the user overrode by editing the quantity', () => {
    expect(promoPayload({ ...promo, quantity: 10 })).toEqual({});
  });
  it('ordinary lines carry nothing extra', () => {
    expect(hasFreeUnits({ quantity: 5 })).toBe(false);
    expect(promoPayload({ quantity: 5 })).toEqual({});
  });
});

describe('invoice total check', () => {
  it('maps reconciliation results to notices', () => {
    expect(reconciliationNotice({ status: 'mismatch', message: 'm' })?.tone).toBe('warn');
    expect(reconciliationNotice({ status: 'matched', message: 'ok' })?.tone).toBe('ok');
    expect(reconciliationNotice({ status: 'not_completed', message: 'n' })?.tone).toBe('info');
    expect(reconciliationNotice(null)).toBeNull();
  });
});

describe('free-unit confirmation (source)', () => {
  const src = readFileSync(resolve(__dirname, '../pages/InvoiceScanner.tsx'), 'utf-8');
  it('asks before posting free units and sends the explicit confirmation', () => {
    expect(src).toMatch(/data-testid="free-units-confirm"/);
    expect(src).toMatch(/confirm_free_units: true/);
  });
});

describe('P0: fractional quantities are never rounded into stock', () => {
  it('detects fractional quantity, paid or free units; whole numbers are unaffected', () => {
    expect(hasFractionalQuantity({ quantity: 2.5 })).toBe(true);
    expect(hasFractionalQuantity({ quantity: 0.75 })).toBe(true);
    expect(hasFractionalQuantity({ quantity: 11, paid_quantity: 10.5, free_quantity: 0.5 })).toBe(true);
    expect(hasFractionalQuantity({ quantity: 3 })).toBe(false);
    expect(hasFractionalQuantity({ quantity: 3.0 })).toBe(false);
    expect(hasFractionalQuantity({ quantity: 11, paid_quantity: 10, free_quantity: 1 })).toBe(false);
    expect(hasFractionalQuantity({ quantity: null })).toBe(false);
  });

  it('explains the block and names the line with its extracted quantity', () => {
    const n = fractionalQuantityNotice([
      { product_name: 'Sugar Loose', quantity: 2.5, unit: 'kg' },
      { product_name: 'Salt 1KG', quantity: 20, unit: 'pcs' },
    ]);
    expect(n).toContain('Fractional stock quantities are not currently supported');
    expect(n).toContain('Nothing has been added to stock');
    expect(n).toContain('Sugar Loose (2.5 kg)');
    expect(n).not.toContain('Salt');
    expect(fractionalQuantityNotice([{ product_name: 'Salt', quantity: 20 }])).toBeNull();
  });

  it('the confirm payload no longer rounds the quantity', () => {
    const src = readFileSync(resolve(__dirname, '../pages/InvoiceScanner.tsx'), 'utf8');
    expect(src).not.toMatch(/Math\.round\(Number\(i\.quantity\)\)/);
    expect(src).toMatch(/selectedItems\.some\(hasFractionalQuantity\)/);
  });
});
