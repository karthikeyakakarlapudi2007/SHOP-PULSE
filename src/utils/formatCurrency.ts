/**
 * @file formatCurrency.ts
 * @description Currency and number formatting helper functions for Shelfora.
 * Belongs in `src/utils/formatCurrency.ts`.
 */

/**
 * Format a numeric value as currency (e.g. ₹4,850.00 or $45.00).
 * 
 * @param amount - The numeric amount to format.
 * @param currency - The ISO currency code (default: 'INR').
 * @param locale - BCP 47 language tag (default: 'en-IN').
 * @returns Formatted currency string.
 */
export function formatCurrency(
  amount: number,
  currency: string = 'INR',
  locale: string = 'en-IN'
): string {
  if (isNaN(amount) || amount === null || amount === undefined) {
    return '₹0.00';
  }

  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
      minimumFractionDigits: 2
    }).format(amount);
  } catch {
    return `₹${amount.toFixed(2)}`;
  }

}

/**
 * Format large numbers into compact human-readable strings (e.g. 1.2K, 3.4M).
 * 
 * @param num - The number to format.
 * @returns Compact formatted string.
 */
export function formatCompactNumber(num: number): string {
  if (isNaN(num)) return '0';
  return new Intl.NumberFormat('en-IN', {
    notation: 'compact',
    compactDisplay: 'short'
  }).format(num);
}

/**
 * Supplier-invoice amounts as printed: 2 decimals, or 3 when the value carries a third decimal
 * (₹62.988), so purchase records, prints and exports never round a printed value to paise.
 */
export function formatPrintedCurrency(amount: number, currency: string = 'INR', locale: string = 'en-IN'): string {
  if (amount === null || amount === undefined || isNaN(amount)) {
    return '₹0.00';
  }
  const places = Math.abs(Math.round(amount * 1000)) % 10 === 0 ? 2 : 3;
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      maximumFractionDigits: places,
      minimumFractionDigits: places,
    }).format(amount);
  } catch {
    return `₹${amount.toFixed(places)}`;
  }
}
