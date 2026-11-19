# Phase 4 – Workstream 4, Phase A: Decimal audit of backend financial calculations

Audit date: 2026-11-19, on `806a877`.

**Implementation status (2026-11-19):** all four decisions in §10 approved; F1 to F12 implemented, see `DECIMAL_IMPLEMENTATION.md`. F4 is resolved by converting spoken prices through text at use. Profit and valuation are deferred (decision 4).
Markers: **[C]** confirmed by reading the code or by running it; **[A]** assumption; **[D]** decision needed.

## 1. Method
- **Sweep:** every `float(`, `round(`, `sum(` and SQL `func.sum` in `backend/services`, `api`, `schemas`, `db` and `core` (49 files), plus float arithmetic without those calls (`*`, `+=`) in the sale and purchase services.
- **Classification:** each hit is financial or non-financial (below).
- **Probe:** the live API was exercised against an **in-memory** database (script kept outside the repository; `backend/shoppulse.db` untouched, SHA-256 `63c44cad…` unchanged).

## 2. Approved rules (target)
- **Decimal:** `Decimal` everywhere money is calculated, built from strings (`Decimal(str(x))`), never from a binary float.
- **Purchase side:** keeps printed precision up to 3 decimals (Phase 3A rule; `_keep_printed_precision`).
- **Sale lines:** line = qty × unit price, unrounded; **each line rounded to 2 dp `ROUND_HALF_UP`**; bill = Σ rounded lines.
- **`ROUND_HALF_UP` wherever currency rounding applies.**

## 3. Probe results: current behaviour through the API [C]

| Scenario | Current result | Approved result |
|---|---|---|
| `POST /purchases` 1 × ₹0.10 + 1 × ₹0.20 | **0.30000000000000004** | 0.30 |
| `POST /purchases` 12 × ₹5.249 | 62.988 | 62.988 (correct; 3 dp kept) |
| `POST /sales` 3 × ₹0.10 | **0.30000000000000004** | 0.30 |
| `POST /sales` 3 × ₹33.335 (line 100.005) | **100.005** (never rounded) | 100.01 |
| `POST /sales` 1 × ₹1.005 + 1 × ₹2.675 | **3.6799999999999997** | 1.01 + 2.68 = **3.69** |
| Voice "3 tea packet 100 rupees" | bill shows ₹100.00 with unit ₹33.33; **the sale recorded from it = ₹99.99** | ₹100.00 |
| Python `round()` on floats | `round(1.005, 2)` = 1.0; `round(2.675, 2)` = 2.67 | 1.01; 2.68 |
| `Decimal.quantize()` with no rounding mode (`ROUND_HALF_EVEN` default) | 1.005 → 1.00; 0.125 → 0.12; 10.245 → 10.24 | 1.01; 0.13; 10.25 |

The fractional examples of rule B (2.500 kg × ₹120, 0.750 kg × ₹44.50) can't be sent to `/sales` yet: fractional quantities return 422 until workstream 2. The rounding rule itself is exercised above with whole quantities and 3-decimal prices.

## 4. Findings: financial calculations

| ID | File / function | Current calculation | Why it is a problem | Proposed Decimal-safe replacement | API / frontend impact |
|---|---|---|---|---|---|
| F1 | `services/sale.py` `create_sale` | `item_total = quantity * unit_price` (floats); `total_amount += item_total`; no rounding; stores the float sum | Binary noise (probed); 3-dp prices never rounded to paise; violates rule B | `line = round_half_up(D(qty) × D(unit_price), 2)`; `total = Σ lines`. Store `unit_price` as given (≤ 3 dp) | `total_amount` becomes a clean 2-dp number (JSON number, same type). **Values with 3-dp prices change** (100.005 → 100.01). Receipts and history show the new totals |
| F2 | `services/purchase.py` `create_purchase` | `item_total = quantity * purchase_price`; `total_amount += item_total`; no rounding | Binary noise (probed) | `total = keep_printed_precision(Σ D(qty) × D(price))`, 3 dp half-up, the same rule as invoice confirmation | Clean values; 3-dp totals unchanged (62.988) |
| F3 | `services/inventory_matcher.py` `_build_matched` (lines 107–112), `match_items_to_inventory` (275–277) | spoken total → `line_total = round(float(total), 2)`, `unit_price = round(line_total / qty, 2)`; else `round(price * qty, 2)`; `subtotal = round(sum(...), 2)`; `tax = 0.0` | Float `round()` is binary; **the derived unit price loses precision, so the sale recorded from a voice bill differs from the bill** (₹100 → ₹99.99, probed) | Decimal: spoken total kept exactly; `unit_price = total / qty` kept to 3 dp (₹33.333); line = round_half_up(qty × unit_price, 2) = ₹100.00, which reproduces the spoken total; subtotal = Σ lines; tax `Decimal(0)` | Voice API `unit_price` may show 3 dp (33.333 instead of 33.33). **[D]** confirm 3-dp unit prices may appear in the voice bill UI. `total_price` / `subtotal` unchanged in format |
| F4 | `services/voice_parser.py` (line 368) | `extracted_price = float(p_str)` | A float from a decimal string is exact enough, but F3 then computes with it | `Decimal(p_str)` (or keep the string) passed to the matcher | None (internal) |
| F5 | `services/insights.py` (lines 93–135, 150–203, 261–306, 378–379) | SQL `SUM(sales.total_amount)` and **`SUM(sale_items.quantity * sale_items.unit_price)`** on REAL; `float()`; `round(float, 2)`; Python `+=` on floats per day | Binary sums and rounding; **per-product revenue = Σ unrounded qty × price, which disagrees with bill totals under rule B** (e.g. 0.75 × 44.5 = 33.375 vs the bill's 33.38) | Read rows and sum `Decimal(str(v))`; per-product revenue = Σ line amounts rounded per line (rule B), computed in Python (no schema change; `sale_items` has no line-total column); quantise half-up at the response | Same JSON fields and types; values may differ by paise from today's |
| F6 | `services/dashboard.py` `today_sales` (20–27) | `COALESCE(SUM(total_amount), 0.0)` then `float()` | Binary aggregate | `Decimal(str(sum))` quantised to 2 dp half-up (or a Python Decimal sum of rows) | None (same number, cleaned) |
| F7 | `services/notification.py` daily summary (248–270) | `float(SUM(...))`, message `₹{:,.2f}` | Binary aggregate; Python's `:.2f` formatting of a float can round a .xx5 value down | Decimal sum, half-up, formatted from the Decimal | Message text may change by a paisa in edge cases |
| F8 | `services/invoice.py` `suggest_misread_decimal_rate` (227–266) | float candidate arithmetic, `abs(q*cand - target) <= 0.011`, `round(cand, 3)`; message formats rates `₹{pp:,.2f}` | Float tolerance comparison; **a 3-dp rate is displayed with 2 dp** in the suggestion text | Decimal candidates and tolerance; format with the printed-precision formatter | Suggestion text only |
| F9 | `services/invoice.py` `extract_metadata` invoice total (380–399) → fallback `total_amount` (719–720) | `float(clean_num)` of the printed total | Low risk (parsed from text), but the value enters the response as a float | `Decimal(clean_num)` → `_num(...)` at the response | None |
| F10 | `services/mrp_lookup.py` `validate_mrp_value` (89–104) | `float(...)` then `round(num, 2)` | Binary rounding (`round(2.675, 2)` = 2.67); **drops a printed 3rd decimal** | `Decimal(str)` and `_keep_printed_precision` (3 dp half-up) | MRP may keep a 3rd decimal (consistent with Phase 3A); JSON number |
| F11 | `services/grocery_ocr/financial/calculation_engine.py` `calculate_line_item` (82–102) | Decimal, but **gross rounded to 2 dp before discount and tax**, and `quantize()` **without a rounding mode (half-even)** | Intermediate rounding (12 × 5.249 → 62.99 before tax); half-even, not half-up | No intermediate rounding: gross exact; discount, tax and final rounded once with `ROUND_HALF_UP` | Validation only (tolerance 0.05): a line could change between "matched" and "mismatch" only at the tolerance edge [A] |
| F12 | `quantize()` without a rounding mode elsewhere: `numeric_parser.py:165`, `column_wise_extractor.py:242–245`, `workbook_parser.py:297–300`, `invoice_reconciliation.py:124` | default half-even | Inconsistent with the approved rule. These sites are parsing beyond 3 dp, decimal-shift comparisons, Excel round trips and a tolerance | Add `rounding=ROUND_HALF_UP` (one shared constant) | None expected; tests will show any change |

## 5. Already Decimal-safe (no change needed) [C]
- `services/invoice.py`:
  - extraction line arithmetic (`resolve_item_arithmetic_py`, `_line_amount_dec`);
  - invoice totals (`tot_amt`);
  - confirm path (purchase line amounts and total, duplicate merge, promo paid-units amounts);
  - `_money` / `_keep_printed_precision` use `ROUND_HALF_UP`;
  - `_dec()` converts floats through `str`.
- `services/invoice_reconciliation.py`: Decimal sums and adjustments (only the tolerance quantize, F12).
- `grocery_ocr/extraction/price_extractor.py`: discounts, tax and GST parts summed as Decimal.
- `cross_validator.py`: Decimal tolerance.
- `float()` at response or storage boundaries **after** quantisation (`invoice.py` lines 193, 207, 511, 545–631, 885, 998–1018; reconciliation 154–181; Excel writer): Decimal → float of a ≤ 15-digit value is exact on the round trip. **Kept as the API boundary.**

## 6. Not financial (no change) [C]
- **Image and OCR measurement:** `document_prep/*` (pixels, angles, quality); `grocery_ocr/processors/*`, `engines/*`, `quality/*`, `table_reconstructor`, `dynamic_schema_generator`, `column_detector`, `visualization`.
- **Confidence and match scores:** OCR confidence averages, `ai/service`, `ai/schemas`, `product_lookup`, `product_matcher`, `mrp_lookup` match confidence, `invoice.py` confidence fields (713–717, 813).
- **Pack-size quantities and counts:** `product_matching.py`, `grocery_classifier.py`, `voice_parser` quantities, `search.py` item counts, and `invoice.py` / `invoice_pipeline.py` token counts.
- **Percentage-range validation:** `column_wise_extractor.py:464`.
- **Legacy, test-only:** `invoice.py` `parse_smart_price_py`, called only by `tests/test_invoices_phase9.py`. No change; could be removed later.

## 7. Topics in the brief with no backend calculation today [C]

| Topic | Finding |
|---|---|
| GST / CGST / SGST | The backend **never calculates** GST for sales or purchases. Invoice GST parts are **extracted as printed** (Decimal) and only summed (F11 validation). Voice bills use `tax = 0.0` (F3) |
| Discounts | Only printed discounts (extracted, Decimal). No discount is calculated for sales |
| Promotions (paid + free) | Confirm amounts use paid units in Decimal (Phase 3A); already safe |
| Profit, inventory valuation | **Not computed in the backend.** Only in the browser (`analyticsService.ts`). Nothing to fix in workstream 4; a backend endpoint belongs in workstream 8 **[D]** |

## 8. API serialisation and storage
- **API:** money fields are `float` in the Pydantic schemas (`schemas/sale.py`, `purchase.py`, `invoice.py`, `voice.py`, `insights.py`, `product.py`). **Proposal:** keep JSON numbers (no contract change), computing in Decimal and converting the **quantised** value to `float` at the response. A ≤ 15-significant-digit decimal round-trips exactly, so 0.3 serialises as `0.3`.
- **Storage:** the DB columns stay `Float` until the separately approved migration (workstream 5). Writing quantised values and reading them back through `Decimal(str(x))` is exact.
- **SQL `SUM` stays binary** until then, which is why F5 to F7 sum in Python Decimal (or quantise the aggregate).

## 9. Proposed implementation (for approval)
1. **One shared money module** (`services/money.py`), reusing `_dec`, `_money` and `_keep_printed_precision` from `invoice.py` (moved, not duplicated):
   - `to_decimal()`: through `str`, rejects NaN and infinity;
   - `round_currency()`: 2 dp half-up;
   - `keep_printed_precision()`: 3 dp half-up;
   - `sale_line_amount()` and `bill_total()`.
2. F1 sales and F2 purchases.
3. F3 and F4 voice.
4. F5 to F7 reporting.
5. F8 to F12 clean-ups.
6. Tests for every approved example, plus API probes like §3, run through the isolated suites.

## 10. Decisions needed [D]
1. **Sale totals change:** existing sales stay as stored. New sales with 3-dp prices are rounded per line, e.g. 100.005 → 100.01. **Historical records are not rewritten.** Confirm.
2. **Voice unit price:** may show 3 dp (₹33.333) so that the recorded sale equals the spoken total. Confirm, or prefer storing the spoken line total separately (needs a column, so the migration).
3. **Reporting values:** insights and dashboard amounts may change by paise because of per-line rounding. Confirm.
4. **Profit and valuation:** frontend-only today. Moving them to the backend is workstream 8, not workstream 4. Confirm the scope.
