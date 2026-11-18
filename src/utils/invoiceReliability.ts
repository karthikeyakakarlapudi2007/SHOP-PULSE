/**
 * Review-screen helpers for the Phase 3A reliability corrections:
 * calculated values, free items, separately printed tax / discount parts and photo warnings.
 * Pure functions (no React), unit-tested in src/tests/invoiceReliability.test.ts.
 */
import type { PhotoAssessment } from '../api/documentPrep';

const PHOTO_EXT = /\.(jpe?g|png|webp|heic|heif|bmp|tiff?)$/i;

/** Photos get a quality check; PDFs and text files do not. */
export function isPhotoFile(file: { name: string; type?: string }): boolean {
  if (file.type && file.type.startsWith('image/')) return true;
  return PHOTO_EXT.test(file.name || '');
}

export interface PhotoWarning {
  title: string;
  messages: string[];
  retake: boolean;
}

/** Warning to show for a directly uploaded photo, or null when the photo is fine. */
export function photoWarning(a: PhotoAssessment | null | undefined): PhotoWarning | null {
  if (!a || !a.quality) return null;
  // Only problems that are not corrected automatically: a direct upload is not enhanced, so
  // messages such as "contrast will be increased" would be misleading here
  const serious = (a.quality.issues || []).filter((i) => i.severity >= 2 && !i.correctable);
  const retake = Boolean(a.retake_recommended);
  if (!retake && serious.length === 0) return null;
  const messages = Array.from(new Set(serious.map((i) => i.message)));
  if (a.document?.cut_off && !messages.some((m) => /outside the photo/i.test(m))) {
    messages.unshift('Part of the invoice is outside the photo.');
  }
  return {
    title: retake
      ? 'This photo is hard to read. Please check every value, or retake the photo.'
      : 'Photo quality is reduced. Please check the values below.',
    messages: messages.length ? messages : [a.quality.summary],
    retake,
  };
}

const FIELD_LABELS: Record<string, string> = {
  quantity: 'quantity',
  purchase_price: 'rate',
  line_total: 'line total',
};

export interface ItemFlagsInput {
  derived_fields?: string[];
  is_free_item?: boolean;
  free_quantity?: number | null;
  cgst_amount?: number | null;
  sgst_amount?: number | null;
  igst_amount?: number | null;
  scheme_discount?: number | null;
  other_discount?: number | null;
  taxable_amount?: number | null;
}

/** Fields that were calculated, not read from the invoice ("quantity", "rate", ...). */
export function calculatedFieldLabels(item: ItemFlagsInput): string[] {
  return (item.derived_fields || []).map((f) => FIELD_LABELS[f] || f);
}

export function isCalculated(item: ItemFlagsInput, field: 'quantity' | 'purchase_price' | 'line_total'): boolean {
  return (item.derived_fields || []).includes(field);
}

/** Money as printed: 2 decimals, or 3 when the invoice prints a third decimal (₹62.988). */
export function formatMoney(v: number | null | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
  const places = Math.abs(Math.round(v * 1000)) % 10 === 0 ? 2 : 3;
  return `₹${v.toLocaleString('en-IN', { minimumFractionDigits: places, maximumFractionDigits: places })}`;
}

/** Round to 3 decimals (the finest printed precision), never to paise. */
export function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}

const money = (v: number) => formatMoney(v);

/** One-line summary of the separately printed parts, e.g. "Taxable ₹363.60 · CGST ₹9.09 · SGST ₹9.09". */
export function componentSummary(item: ItemFlagsInput): string {
  const parts: string[] = [];
  const add = (label: string, v: number | null | undefined) => {
    if (typeof v === 'number') parts.push(`${label} ${money(v)}`);
  };
  add('Taxable', item.taxable_amount);
  add('CGST', item.cgst_amount);
  add('SGST/UTGST', item.sgst_amount);
  add('IGST', item.igst_amount);
  if (typeof item.scheme_discount === 'number' && item.scheme_discount !== 0) add('Scheme disc', item.scheme_discount);
  if (typeof item.other_discount === 'number' && item.other_discount !== 0) add('Other disc', item.other_discount);
  return parts.join(' · ');
}


// ------------------------------------------------------------------- promotions (paid + free units)

export interface PromoInput {
  quantity: number | null;
  paid_quantity?: number | null;
  free_quantity?: number | null;
  is_free_item?: boolean;
}

/** Line posts free units to stock (needs explicit confirmation before posting). */
export function hasFreeUnits(item: PromoInput): boolean {
  return Boolean(item.is_free_item) || (typeof item.free_quantity === 'number' && item.free_quantity > 0);
}

/** "10 paid + 1 free" for a promotion line, "6 free" for a printed free line, else null. */
export function promoBreakdown(item: PromoInput): string | null {
  if (item.is_free_item && typeof item.quantity === 'number') return `${item.quantity} free (printed rate ₹0.00)`;
  if (typeof item.free_quantity === 'number' && item.free_quantity > 0 && typeof item.paid_quantity === 'number') {
    return `${item.paid_quantity} paid + ${item.free_quantity} free = ${item.paid_quantity + item.free_quantity} received`;
  }
  return null;
}

/** Paid / free fields for the confirm request; dropped when the user changed the quantity so the
 *  breakdown no longer adds up (the edited quantity is then posted as entered). */
export function promoPayload(item: PromoInput): { paid_quantity?: number; free_quantity?: number; is_free_item?: boolean } {
  const out: { paid_quantity?: number; free_quantity?: number; is_free_item?: boolean } = {};
  if (item.is_free_item) out.is_free_item = true;
  if (typeof item.paid_quantity === 'number' && typeof item.free_quantity === 'number' && item.free_quantity > 0
      && typeof item.quantity === 'number' && Math.abs(item.paid_quantity + item.free_quantity - item.quantity) < 1e-9) {
    out.paid_quantity = item.paid_quantity;
    out.free_quantity = item.free_quantity;
  }
  return out;
}

// ------------------------------------------------------------------- whole-unit stock (P0)

export interface QuantityInput {
  product_name?: string;
  quantity?: number | null;
  unit?: string | null;
  paid_quantity?: number | null;
  free_quantity?: number | null;
}

const isWhole = (v: number) => Math.abs(v - Math.round(v)) < 1e-9;

/**
 * True when a line's quantity (or its paid / free units) is not a whole number. Stock is tracked in
 * whole units, so such a line is never rounded: confirmation is blocked until the user corrects it.
 */
export function hasFractionalQuantity(item: QuantityInput): boolean {
  return [item.quantity, item.paid_quantity, item.free_quantity].some((v) => typeof v === 'number' && !isWhole(v));
}

/** Blocking message for lines with a fractional quantity; null when there are none. */
export function fractionalQuantityNotice(items: QuantityInput[]): string | null {
  const lines = items.filter(hasFractionalQuantity);
  if (lines.length === 0) return null;
  const list = lines
    .map((i) => `${i.product_name || 'Unnamed item'} (${i.quantity ?? '?'}${i.unit ? ` ${i.unit}` : ''})`)
    .join('; ');
  return (
    `Fractional stock quantities are not currently supported: stock is tracked in whole units. ` +
    `Nothing has been added to stock. Correct the quantity of ${list} — for example enter whole packs or bags ` +
    `and adjust the rate — or deselect ${lines.length > 1 ? 'these lines' : 'the line'}.`
  );
}

// ------------------------------------------------------------------- grand-total reconciliation

export interface TotalReconciliation {
  status: 'matched' | 'mismatch' | 'not_completed';
  message: string;
  printed_total?: number | null;
  lines_total?: number | null;
}

export function reconciliationNotice(r: TotalReconciliation | null | undefined): { tone: 'ok' | 'warn' | 'info'; text: string } | null {
  if (!r || !r.status) return null;
  if (r.status === 'mismatch') return { tone: 'warn', text: r.message };
  if (r.status === 'matched') return { tone: 'ok', text: r.message };
  return { tone: 'info', text: r.message };
}
