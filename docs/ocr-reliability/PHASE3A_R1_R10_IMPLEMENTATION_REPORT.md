# Phase 3A – R1–R10 implementation report

**Status: implemented and tested, NOT committed (awaiting your review).**

All results come from executed runs on 2026-11-17. Repository fixtures, synthetic pages and simulated
captures are reported separately. They are not real-world accuracy, and nothing is claimed as 100%.

## 1. Fixes implemented

| # | Correction | What changed |
|---|---|---|
| R1 | Calculated values are never "verified" | A quantity, rate or line total that is calculated (amount ÷ rate, amount ÷ quantity, quantity × rate, the pipeline's own calculated amount, or cases × units per case) is listed in `derived_fields`, explained in `validation_issues` and flagged for review. "Verified" now requires quantity, rate and amount all **read** and agreeing. The arithmetic uses `Decimal` with half-up rounding. Discounts are now included in the arithmetic check (previously ignored). Silent "repairs" are replaced by suggestions: quantity ÷10, MRP or selling price ÷100. A possible quantity reading is offered as a one-click `suggested_quantity`. |
| R2 | Only money-like values become amounts | The amount fallback uses only a value with a decimal point, from a column with no identified role, and the line is flagged. HSN, serial, quantity, units per case, cases, GST % and tax / discount / taxable / price columns are never used. Table-rule artefacts (`960.00 |`) are ignored. The API's "last number in the row" amount guess is removed: if no amount is identified, the line total stays empty or is marked calculated, and the line is flagged. Positional price guessing is limited to unlabelled or price columns and flagged. |
| R6 | Tax and discount parts kept separately | CGST, SGST/UTGST, IGST and cess are kept per column, and their sum is the tax. Every discount column (scheme, RS / other, cash, trade) is kept; previously a second discount column **overwrote** the first. A CGST % + SGST % pair gives the total GST rate. Taxable and net amounts are separate response fields. These values survive the Excel audit-workbook round trip (carried forward by row position and matching name). |
| R7 | Three-decimal values | Printed values keep up to 3 decimals in parsing and in the workbook round trip (`62.988`, `7.143`). Database: assessment only (section 3); no migration. |
| R3 | Alternative OCR segmentation | When the default reading (PSM 3) breaks ≥ 3 numbers at the decimal point, the page is also read with the existing `fallback_ocr_psm` (6). The alternative is kept only with clearly more whole money values (≥ +3 or +10%). The decision and counts are recorded in `ocr_psm_selection`, and `diagnostics.ocr_psm` reports the mode used. |
| R4 | Multi-line headings | A header-like row directly above or below the heading row (no data values; at least 2 heading words, or 1 plus overlap) is merged through the existing stacked-heading logic and kept out of the data. A sub-label under a group heading ("IGST" over "% / Amount") takes the group's meaning, so "Amount" there is not taken as the line total. |
| R5 | Cases, pieces, units per case | New column roles `cases` and `units_per_case`; heading words: UPC, Cs, Cases, QTYSOLD, NETRATE, TOTAMOUNT, Base Rate, BASIC.RT, S/UTGST Amt, RS Disc. Quantity = cases × units per case + loose pieces only when all are read and the quantity column holds loose pieces; the result is marked calculated and flagged. Cases without units per case → quantity left empty and flagged. `0/12` means cases / pieces. `a+b` means paid + free: the free units are reported, never added automatically. A "UPC" value of 8+ digits is a barcode. |
| R9 | Name line + numbers line | A numbers-only line directly under a name-only line is joined to it, never when either has its own serial, name or numbers. A line with its own HSN code or any value is never folded into the product above (this previously merged a bundle heading into the previous product). |
| R8 | Cropped document outlines | An outline with 1–3 corners on the photo frame is rejected only with evidence of cropping: text **inside** the outline runs into that frame edge, and that edge is paper-coloured (≥ 0.6 of paper lightness; measured 0.68–0.87 on cut pages vs 0.37 on a textured background). The photo is then not reshaped, the original is kept, and a retake is advised (`cut_off` issue). Full-frame scans and pages that merely touch the frame are unaffected. |
| R10 | Direct-upload photo warnings | New `POST /api/v1/document-prep/assess`: the same grading and cut-off detection as the camera flow, no OCR, about 0.45 s. For direct photo uploads the scanner runs it alongside extraction. It shows a warning card with the problems that are not corrected automatically, plus a "Retake the photo" button. PDFs and text files are not checked. `/invoices/extract` is unchanged. |
| Stage 4 | Bundles and free products | Bundle headings ("(With Free Product)", or `a+b` quantities with no rate or tax) become `bundle_notes`, never stock lines. A printed free line (rate 0.00, amount 0.00, quantity > 0) is kept as its own line with `is_free_item`, its printed quantity and a zero rate, and is always reviewed. Confirmation accepts rate 0 only for free items. No cost is invented or redistributed. |

## 2. Files modified

**Backend:**
- `services/invoice.py`
- `schemas/invoice.py` (additive optional fields)
- `api/routes/document_prep.py` (new `/assess`)
- `services/document_prep/{document_detector,pipeline,quality}.py`
- `services/grocery_ocr/extraction/{numeric_parser,price_extractor,column_wise_extractor,dynamic_schema_generator,header_intelligence,header_recognizer,table_reconstructor}.py`
- `services/grocery_ocr/{pipeline/invoice_pipeline,schemas/table,excel/workbook_parser}.py`

**Frontend:**
- `src/pages/InvoiceScanner.tsx`
- `src/api/documentPrep.ts`
- `src/utils/invoiceReliability.ts` (new)

**Tests:**
- `backend/tests/test_ocr_reliability_r1_r10.py` (new, 58 tests)
- `backend/tests/test_column_wise_extractor.py`: one test updated to the approved behaviour (the quantity "repair" is now a suggestion)
- `backend/tests/test_document_prep_api.py` (+2)
- `src/tests/invoiceReliability.test.ts` (new, 7)
- `scripts/e2e/direct_upload_warning_check.cjs` + `prepare_warning_assets.py` (new)

**Results:** `docs/ocr-reliability/after_phase3a_r1_r10.{json,md}`.

**Unchanged:**
- OCR engine and worker;
- `/invoices/extract` route;
- HEIC loader and PDF builder;
- authentication, inventory CRUD, Voice-to-Bill;
- database schema and records.

## 3. Database precision assessment (R7)

- **Current schema.**
  - `products.purchase_price / selling_price / mrp`, `purchases.total_amount`, `purchase_items.purchase_price / line_amount / mrp` and `sale_items.unit_price` are SQLAlchemy `Float`: SQLite `REAL`, or PostgreSQL `double precision`.
  - `purchase_items.quantity`, `sale_items.quantity` and `products.current_stock` are `Integer`.
- **Precision limitations.**
  - A double keeps about 15–16 significant digits, so a 3-decimal price or amount is stored and read back as the same printed value (62.988 → 62.988). Storage itself loses nothing.
  - Sums are binary floating point, not exact decimals.
  - The confirm path rounds to 2 decimals where it calculates: the fallback `line_amount = round(qty × price, 2)` (12 × 7.143 = 85.716 → 85.72) and `purchases.total_amount = round(sum, 2)`.
  - A printed `line_amount` is stored as given (3 decimals kept).
  - Quantities are whole stock units, enforced by the confirm validator. A loose quantity such as 2.5 kg cannot be stocked; this is pre-existing behaviour.
- **Proposed migration (NOT executed).**
  - One Alembic revision altering the money columns to `Numeric(14,3)`.
  - SQLite uses `batch_alter_table` (table copy); PostgreSQL uses `ALTER COLUMN … TYPE numeric(14,3) USING round(col::numeric, 3)`.
  - The confirm code would sum with `Decimal` and round half-up to 3 decimals.
  - Quantity → `Numeric(12,3)` would be a separate decision, because it changes stock logic and the whole-unit rule.
- **Existing-record impact.**
  - Every existing value is rewritten rounded to 3 decimals; values such as 13.280000000000001 become 13.280.
  - No rows are added or deleted.
  - Code reading these columns receives `Decimal` instead of `float`, so services that do arithmetic on them need small changes.
- **Rollback plan.**
  - Back up the database file / dump before upgrading.
  - Alembic `downgrade` alters the columns back to `Float`, which is lossless for 3-decimal values.
  - Code changes are reverted together with the revision.
- **Needs your approval:** the migration, and changing confirm-time rounding from 2 to 3 decimals. Both change stored data.

## 4. Before / after – repository datasets (same inputs; NOT real-world evidence)

A line is **fully correct** when product name, quantity, rate and amount are all correct.

| | Fixtures (32 files / 160 lines) | Synthetic (17 / 121) | Simulated captures (81 / 416) |
|---|---|---|---|
| Fully correct lines | 145 → **145** | 104 → **102** | 250 → **243** |
| Lines found | 155 → 155 | 114 → 114 | 317 → **321** |
| Product name / quantity | 145 / 155 → 145 / 155 | 107 / 112 → 107 / 110 | 267 / 290 → 262 / **293** |
| Rate / MRP / amount | 152 / 95 / 155 → same | 112 / 114 / 114 → same | 287 / 120 / 303 → **297 / 123 / 304** |
| **Wrong qty/rate/amount shown without a review flag** | 0 → 0 | 0 → 0 | **12 → 1** |
| Non-invoice lines shown without a flag | 0 → 0 | 0 → 0 | 8 → **1** |
| Decimal corruption (×10ⁿ) | 0 → 0 | 0 → 0 | 14 → **7** |
| Values invented for unprinted fields | 3 → 3 (calculated rates on TC04, now flagged as calculated) | 0 → 0 | 0 → 0 |
| Median extraction time | 1.44 → 1.12 s | 3.06 → 2.37 s | 2.67 → 2.34 s |

**Regressions, reported separately and attributed line by line:**

| Lines | Cause | Status |
|---|---|---|
| synthetic −2 (Toor Dal ×2), simulated −3 (TC13 SUGAR ×2, SOYABEAN) | The silent quantity "repair" (printed 2.5 read as 25 → divided by 10) was removed as required. The reading is kept, flagged, with **"Use 2.5 as quantity"** offered. | Intended |
| simulated −6 (TC13 upside down), −1 (TC13 tilted) | R8: these pages really are cut off at the photo edge (verified visually), so they are no longer reshaped and a retake is advised. | Intended per R8 |
| simulated +3 (TC13 low light) | R2 / R4 | Improvement |

The one silent error left (TC15 perspective: quantity 2.50 → 250 **and** amount 350.00 → 35000, consistent arithmetic) was silent before too. Only a printed-grand-total check would catch it (Phase 3A plan item C2, not approved).

## 5. Financial accuracy – real photos (private, not committed)

Four supplied photos, 899 × 1599 WebP recompressions. No camera originals were provided. Expected values exist only for the 16-column GST invoice (photo A, verified against its printed totals).

| Photo | Before | After |
|---|---|---|
| A – 16-column GST invoice, page 1 of 2 | 13 lines, all flagged, amounts were HSN codes / UPC numbers | **No lines** (no garbage amounts); page detected as cut off at the right edge → not reshaped, **retake advised**. Correct lines: 0 / 18 before and after |
| B – dot-matrix bill | Direct upload: **3 wrong lines shown as verified** | 4 lines, **all flagged**; cut off → retake advised |
| C – laser GST invoice | 0 lines | 0 lines; retake advised (poor capture) |
| D – thermal delivery challan (23 lines) | 2–3 lines; amounts were serial numbers | 6 lines, all flagged; 5 with correct qty × rate = amount. Names damaged by handwritten ticks |

A synthetic render of photo A's table layout (same structure, clean print) went from **0 / 18 to 18 / 18** lines. That shows the table logic now handles this layout; recognising the low-resolution photo itself remains the limit.

## 6. Regression test results (executed)

| Suite | Result |
|---|---|
| Full backend `pytest` | **629 passed, 0 failed, 7 skipped** (the same 7 pre-existing fixture-file skips) |
| New R1–R10 / Stage 4 tests (incl. 2 end-to-end runs with real OCR on a generic rendered GST invoice) | 58 passed (+2 `/assess` API tests) |
| Frontend `vitest` | **86 passed** (13 files) |
| TypeScript `tsc -b` | passed |
| `oxlint` on changed frontend files | no findings |
| Production build | passed |
| Mobile capture e2e (Playwright) | 25 / 25 |
| Invoice metadata integrity e2e | 11 / 11 (run before the final wording-only change to the direct-upload warning; that change is covered by vitest and the new e2e) |
| Direct-upload warning e2e (new) | 6 / 6 |

## 7. V-model traceability

| Correction | Verification (unit / integration) | Validation (measured) |
|---|---|---|
| R1 | `test_r1_*` (calculated quantity / rate flagged, incorrect calculated values, Decimal half-up, discounts in arithmetic, pipeline-calculated total, suggested quantity) | silent errors 12 → 1 (simulated); photo B no longer silent |
| R2 | `test_r2_*` (money-like, HSN / UPC / GST never amounts, unlabelled amount flagged, empty amount flagged, MRP ÷100 suggested) | photo A: no HSN / UPC amounts; challan amounts correct |
| R3 | `test_r3_*` (fallback when split, not when intact, not unless clearly better) | clean render: 0 → 134 whole amounts |
| R4 | `test_r4_*` (two-line headings both orders, data row never a heading, sub-label under group) | fixture TC14 kept correct; render 18 / 18 |
| R5 | `test_r5_*` (roles, cases × units, zero cases, missing units, 0/12, 10+1, barcode UPC) | case lines 60 / 108 / 36 / 40 calculated and flagged |
| R6 | `test_r6_*` (CGST / SGST, two discounts, taxable vs net, CGST% + SGST%, API fields, carry-forward) | render: tax and discount parts exact |
| R7 | `test_r7_*` (parser, Excel round trip, API) | 3-decimal challan amounts preserved |
| R8 | `test_r8_*` (cropped page, whole page, full-frame scan, cut-off → retake) | simulated: 3 true cut-offs, no false ones after the paper check |
| R9 | `test_r9_*` (join, no merge of neighbours, own HSN not a continuation) | challan: 6 lines |
| R10 | `test_r10_*`, `/assess` API tests, vitest, e2e 6 / 6 | photos A / B / C retake, D none |
| Stage 4 | `test_stage4_*` (bundle heading, quantities-only heading, free line, "FREE" in a paid name, API review, zero-rate confirm) | e2e generic invoice |

## 8. Remaining limitations

- **The low-resolution copy of photo A still cannot be read.** Base Rate is under handwritten X marks, and about half the numbers are lost. The camera originals and page 2 are still needed.
- **Column boundaries:** with left-aligned headings over right-aligned numbers, a narrow column (Cs) can fall into its neighbour. The quantity is then calculated and flagged, never silently wrong (pinned by a test). Not changed: column-boundary logic was outside the approved scope.
- A two-letter "EA" (each) heading is not recognised: "ea" matched OCR noise and cost 8 lines in testing, so it was removed.
- The cut-off evidence uses a lightness ratio of 0.6, measured on these images only.
- **Single-line "a+b" (paid + free):** the free units are reported, not stocked; you decide.
- Loose decimal quantities (2.5 kg) cannot be stocked (whole-unit rule).
- Grand-total reconciliation (C2) is not implemented. One silent simulated error of that kind remains.
- The Excel round trip still drops `review_status` / classification fields not needed here (pre-existing, unchanged).
- Indian-language invoices remain untested (OCR is English only).

## 9. Changes requiring additional approval

1. The DB migration to `Numeric(14,3)` and 3-decimal confirm rounding (section 3).
2. Grand-total reconciliation (C2) for consistent decimal loss.
3. Whether paid + free units ("10+1") and free items should enter stock automatically, at zero cost.
4. Column-boundary refinement for left-aligned headings.
5. Committing this work (not committed, per your instruction).
