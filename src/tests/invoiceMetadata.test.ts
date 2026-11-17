/**
 * Invoice review header details: never invented, editable, validated before confirmation.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  confirmHeaderPayload,
  invoiceDateError,
  isValidInvoiceDate,
  missingInvoiceDetails,
  normalizeInvoiceMetadata,
} from '../utils/invoiceMetadata';

describe('normalizeInvoiceMetadata', () => {
  it('keeps extracted values and marks them detected', () => {
    const m = normalizeInvoiceMetadata({
      supplier_name: 'Sri Lakshmi Wholesale Traders',
      invoice_number: 'INV-00427',
      invoice_date: '08/10/2026',
    });
    expect(m.supplier_name).toBe('Sri Lakshmi Wholesale Traders');
    expect(m.invoice_number).toBe('INV-00427');
    expect(m.invoice_date).toBe('08/10/2026');
    expect(m.detected).toEqual({ supplier_name: true, invoice_number: true, invoice_date: true });
  });

  it('leaves missing values empty instead of inventing them', () => {
    const m = normalizeInvoiceMetadata({ supplier_name: null, invoice_number: undefined, invoice_date: '  ' });
    expect(m.supplier_name).toBe('');
    expect(m.invoice_number).toBe('');
    expect(m.invoice_date).toBe('');
    expect(m.detected).toEqual({ supplier_name: false, invoice_number: false, invoice_date: false });
  });
});

describe('invoice date validation', () => {
  it.each(['08/10/2026', '8-10-26', '08.10.2026', '2026-10-08', '12 Oct 2026', '12-Oct-2026'])('accepts %s', (d) => {
    expect(isValidInvoiceDate(d)).toBe(true);
    expect(invoiceDateError(d)).toBeNull();
  });
  it.each(['31/02/2026', '12/31/2026', 'tomorrow', '2026-13-01'])('rejects %s with a clear message', (d) => {
    expect(isValidInvoiceDate(d)).toBe(false);
    expect(invoiceDateError(d)).toMatch(/DD\/MM\/YYYY/);
  });
  it('treats an empty date as missing, not invalid', () => {
    expect(invoiceDateError('')).toBeNull();
  });
});

describe('manual entry and confirmation payload', () => {
  it('lists missing details so the user can enter or confirm them', () => {
    expect(missingInvoiceDetails({ supplier_name: 'Balaji', invoice_number: '', invoice_date: ' ' })).toEqual([
      'invoice_number',
      'invoice_date',
    ]);
    expect(missingInvoiceDetails({ supplier_name: 'A', invoice_number: 'B', invoice_date: '01/01/2026' })).toEqual([]);
  });
  it('sends typed values trimmed and omits empty ones (never placeholders)', () => {
    expect(confirmHeaderPayload({ supplier_name: ' Balaji Traders ', invoice_number: '', invoice_date: '08/10/2026' })).toEqual({
      supplier_name: 'Balaji Traders',
      invoice_date: '08/10/2026',
    });
    expect(confirmHeaderPayload({ supplier_name: '', invoice_number: '', invoice_date: '' })).toEqual({});
  });
});

describe('review screen source', () => {
  it('contains no invented invoice number, supplier or date fallbacks', () => {
    const src = readFileSync(resolve(__dirname, '../pages/InvoiceScanner.tsx'), 'utf-8');
    expect(src).not.toMatch(/Generic Supplier/);
    expect(src).not.toMatch(/'INV-'\s*\+/);
    expect(src).not.toMatch(/Math\.random/);
    expect(src).not.toMatch(/invoice_date:\s*data\.invoice_date\s*\|\|/);
  });
});
