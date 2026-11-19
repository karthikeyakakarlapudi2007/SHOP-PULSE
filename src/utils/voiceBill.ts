/**
 * Voice-to-Bill line helpers: how a recognised line becomes a cart line, and manual price correction.
 * A price spoken (or corrected by the user) is carried as the line's own unit price, so the cart, the
 * displayed bill and the saved sale all use it; the catalogue price applies only when no price was said.
 */
import type { MatchedVoiceItem } from '../api/voice';
import type { CartItem, Product } from '../types';
import { catalogPrice, lineTotal } from './cartPricing';

/** True when the line's price must be kept instead of the catalogue price. */
export function hasAgreedPrice(item: MatchedVoiceItem, product?: Product): boolean {
  if (item.price_source === 'spoken' || item.price_source === 'edited') return true;
  if (item.price_source === 'catalogue') return false;
  // Older responses without price_source: keep any price that differs from the catalogue
  const exact = item.unit_price_exact ?? item.unit_price;
  return product ? Math.abs(exact - catalogPrice(product)) > 1e-9 : false;
}

/** Exact unit price of a line: quantity x this, rounded to paise, gives the line total. */
export function exactUnitPrice(item: MatchedVoiceItem): number {
  if (typeof item.unit_price_exact === 'number') return item.unit_price_exact;
  return item.quantity > 0 ? item.total_price / item.quantity : item.unit_price;
}

export function voiceLineToCartItem(item: MatchedVoiceItem, product: Product): CartItem {
  const line: CartItem = { product, quantity: item.quantity };
  if (hasAgreedPrice(item, product)) {
    line.unitPrice = exactUnitPrice(item);
    line.priceSource = item.price_source === 'edited' ? 'edited' : 'spoken';
  }
  if (item.spoken_quantity) line.spokenQuantity = item.spoken_quantity;
  return line;
}

/** A line whose total the user corrected: the unit price follows the new total; the quantity is unchanged. */
export function withEditedLineTotal(item: MatchedVoiceItem, total: number): MatchedVoiceItem {
  const paise = lineTotal(1, total); // to the paisa, half-up
  const exact = item.quantity > 0 ? paise / item.quantity : paise;
  return {
    ...item,
    total_price: paise,
    unit_price_exact: exact,
    unit_price: Math.round(exact * 1000) / 1000,
    price_source: 'edited',
  };
}
