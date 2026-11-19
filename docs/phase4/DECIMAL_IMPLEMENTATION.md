# Phase 4 – Workstream 4: Decimal-safe backend money (implemented, uncommitted)

Implements `DECIMAL_AUDIT.md` F1 to F12 with the four approved decisions. No schema change, no migration, no data rewritten.

## Rules in code (`backend/services/money.py`)
- **`to_decimal`:** builds a Decimal from text; floats go through their shortest representation (0.1 → `0.1`). NaN, infinity, booleans and unparsable values give `None`.
- **Rounding:** `round_currency` is 2 dp and `round_price` 3 dp, both `ROUND_HALF_UP`; `quantize_half_up` takes any number of places.
- **`keep_printed_precision`:** up to 3 dp (purchase side).
- **Sale rule:** `sale_line_amount` = quantity × unit price, rounded once to 2 dp; `bill_total` = Σ rounded lines.
- **Helpers:** `sum_decimal` (exact sum), `to_number` (float at the API or storage boundary, after rounding), `format_rupees` (half-up text, keeps a printed 3rd decimal).
- **Moved, not duplicated:** the invoice service's `_dec`, `_money`, `_num` and `_keep_printed_precision` now point at these functions under their old names.

## Changes

| Finding | Where | Now |
|---|---|---|
| F1 sales | `services/sale.py` | per-line half-up to paise; bill = Σ lines. Unit prices stored as given (3 dp kept) |
| F2 manual purchases | `services/purchase.py` | Decimal Σ qty × price, 3 dp kept |
| F3, F4 voice | `services/inventory_matcher.py`, `schemas/voice.py` | Spoken amount = line total. `unit_price` = 3-dp display value (₹33.333); **new optional `unit_price_exact`** (10 dp) for the sale, so qty × price reproduces the spoken total (₹100.00, not ₹99.99). Subtotal and total = Σ lines. Spoken prices are converted through text (`to_decimal`) |
| F5 insights | `services/insights.py` | Period totals, average ticket and daily trend summed in Decimal from stored bill totals. **Per-product revenue = Σ per-line rounded amounts**, so it matches the bills. Growth and text in Decimal |
| F6 dashboard | `services/dashboard.py` | today's sales: Decimal sum of stored totals |
| F7 daily notification | `services/notification.py` | Decimal sum, text from the rounded Decimal |
| F8 misread rate | `services/invoice.py` | Decimal candidates and tolerance; text keeps a 3rd decimal (₹58.575) |
| F9 printed-total fallback | `services/invoice.py` `extract_metadata` | parsed from text as Decimal (3 dp kept) |
| F10 MRP | `services/mrp_lookup.py` | Decimal; printed 3rd decimal kept, half-up |
| F11 OCR validation | `grocery_ocr/financial/calculation_engine.py` | components exact; the final amount rounded once, half-up (components still reported rounded half-up) |
| F12 explicit rounding | `numeric_parser.py`, `column_wise_extractor.py`, `workbook_parser.py`, `invoice_reconciliation.py` (formatter now `format_rupees`) | `ROUND_HALF_UP` everywhere money is quantised |

Unchanged on purpose:
- non-financial floats: OCR geometry, confidence and match scores, pack sizes, counts;
- GST, CGST, SGST and discounts: not calculated by the backend;
- profit and valuation: frontend, deferred (decision 4);
- historical records.

## API compatibility
- **Unchanged contracts:** every money field is still a plain JSON number with the same names and response structures.
- **One additive optional field:** `unit_price_exact` on voice matched items. Clients that ignore it still work.
- **Values that change for new data only:**
  - sale totals with 3-dp prices (100.005 → 100.01);
  - float noise removed (0.30000000000000004 → 0.3);
  - voice unit price shown to 3 dp;
  - report amounts follow per-line rounding (paise-level).

## Tests (executed 2026-11-19)
- **New: `backend/tests/test_decimal_money.py`, 34 passed.** It covers:
  - the approved table (purchase 0.10 + 0.20 = 0.30; sale 3 × 0.10 = 0.30; 3 × 33.335 = 100.01; 1.005 + 2.675 = 3.69; voice 3 for ₹100 → saved 100.00; purchase 12 × 5.249 = 62.988; 1.005 / 2.675 / 0.125 → 1.01 / 2.68 / 0.13);
  - multiple lines and API compatibility;
  - dashboard, insights (per-product revenue equals the bills) and the daily notification;
  - historical records unchanged;
  - MRP 3rd decimal, the printed-total fallback, misread rate, and the validation engine (1.005 → 1.01).
- **Full suites:** backend **850 passed, 7 skipped, 0 failed** (previously 816); Vitest 111 passed (15 files); TypeScript, lint (exit 0; the same 12 pre-existing warning files) and build pass.
- **Browser checks (isolated launcher):** 25/25, 12/12, 6/6, 17/17, 18/18, 16/16.
- **OCR dataset re-run** (fixtures, synthetic, simulated; in-memory DB): **zero differences** in any extracted value, suggestion, status or header compared with workstream 1.

## Known limitations
- **App UI and spoken prices:** the voice bill puts **product + quantity** into the cart, and the cart posts the **catalogue selling price** (`VoiceBillModal.tsx` → `Sales.tsx`). Spoken prices therefore don't reach saved sales through the app today; this was true before as well. The backend now makes a sale exact for any client that posts `unit_price_exact`. Carrying spoken prices into the cart is a frontend Voice-to-Bill change that needs approval (workstream 6/7).
- **Storage is still REAL:**
  - money columns stay `Float` until the separately approved migration;
  - values are rounded before storage and read back exactly through `to_decimal`;
  - report sums are done in Python Decimal over the stored rows (no binary SQL SUM). For very large shops this reads every sale row of the period [A: fine at shop scale].
- **No stored sale-line total:** `sale_items` has no line-total column, so per-line amounts are recomputed by the same rule on read (consistent with the bill). Storing them needs the migration.
- **Frontend previews:** they still use JavaScript numbers (workstream 6, `decimalCalc.ts`); the backend's stored values are authoritative.
