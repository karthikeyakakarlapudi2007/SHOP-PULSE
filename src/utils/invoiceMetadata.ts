/**
 * Invoice header details (supplier, invoice number, invoice date) on the review screen.
 *
 * Values are taken only from the extraction or typed by the user; nothing is invented when
 * OCR did not find a value. Missing values stay empty and are marked "Not detected".
 */

export type InvoiceMetaField = 'supplier_name' | 'invoice_number' | 'invoice_date';

export interface InvoiceMetadata {
  supplier_name: string;
  invoice_number: string;
  invoice_date: string;
  /** Which fields were found on the invoice by OCR (false = not detected). */
  detected: Record<InvoiceMetaField, boolean>;
}

export const META_LABELS: Record<InvoiceMetaField, string> = {
  supplier_name: 'Supplier',
  invoice_number: 'Invoice number',
  invoice_date: 'Invoice date',
};

const clean = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');

/** Metadata from an /invoices/extract response; missing values stay empty strings. */
export function normalizeInvoiceMetadata(data: {
  supplier_name?: unknown;
  invoice_number?: unknown;
  invoice_date?: unknown;
}): InvoiceMetadata {
  const supplier_name = clean(data?.supplier_name);
  const invoice_number = clean(data?.invoice_number);
  const invoice_date = clean(data?.invoice_date);
  return {
    supplier_name,
    invoice_number,
    invoice_date,
    detected: {
      supplier_name: supplier_name !== '',
      invoice_number: invoice_number !== '',
      invoice_date: invoice_date !== '',
    },
  };
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

function isRealDate(y: number, m: number, d: number): boolean {
  if (m < 1 || m > 12 || d < 1) return false;
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d;
}

/**
 * Same rule as the backend (schemas/invoice.py parse_invoice_date): day-first invoice dates
 * (DD/MM/YYYY, DD-MM-YY, DD.MM.YYYY), year-first dates and "12 Oct 2026". Must be a real date.
 */
export function isValidInvoiceDate(value: string): boolean {
  const text = value.trim();
  let m = text.match(/^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$/);
  if (m) return isRealDate(+m[1], +m[2], +m[3]);
  m = text.match(/^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})$/);
  if (m) {
    const y = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return isRealDate(y, +m[2], +m[1]);
  }
  m = text.match(/^(\d{1,2})[\s-]+([A-Za-z]{3})[A-Za-z]*[\s\-,]+(\d{2}|\d{4})$/);
  if (m) {
    const mon = MONTHS.indexOf(m[2].toLowerCase()) + 1;
    const y = m[3].length === 2 ? 2000 + +m[3] : +m[3];
    return mon > 0 && isRealDate(y, mon, +m[1]);
  }
  return false;
}

/** Validation message for the date field, or null when it is empty or valid. */
export function invoiceDateError(value: string): string | null {
  if (!value.trim()) return null;
  return isValidInvoiceDate(value) ? null : 'Not a valid date. Use DD/MM/YYYY, for example 08/10/2026.';
}

/** Header details that are still empty (they are allowed, but the user is asked to confirm). */
export function missingInvoiceDetails(meta: Pick<InvoiceMetadata, InvoiceMetaField>): InvoiceMetaField[] {
  return (['supplier_name', 'invoice_number', 'invoice_date'] as InvoiceMetaField[]).filter((f) => !meta[f].trim());
}

/** Confirm-request header fields: empty values are omitted, never replaced. */
export function confirmHeaderPayload(meta: Pick<InvoiceMetadata, InvoiceMetaField>) {
  const out: Partial<Record<InvoiceMetaField, string>> = {};
  for (const f of ['supplier_name', 'invoice_number', 'invoice_date'] as InvoiceMetaField[]) {
    const v = meta[f].trim();
    if (v) out[f] = v;
  }
  return out;
}
