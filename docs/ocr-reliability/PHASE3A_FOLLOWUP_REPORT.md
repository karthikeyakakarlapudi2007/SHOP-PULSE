# Phase 3A follow-up and P0 — implementation report

All results below come from runs executed on 2026-11-18. Repository fixtures, synthetic pages and simulated
captures are test data, **not real-world accuracy**. Nothing is claimed as 100%.

## 1. What was implemented

| # | Decision | Implementation |
|---|---|---|
| 1 | Grand-total reconciliation (C2), warning only | `services/invoice_reconciliation.py`. Finds the printed total from strong labels only (Grand Total, Net Payable, Net Amount, Invoice Total, Bill Amount, …), never from Qty/Tax/Sub Total/Page Total/“in words” lines. Uses printed round-off, charges, tax, TCS, discount and credit lines when they explain the difference. Tolerance max(₹1, 0.1%). Result: `matched`, `mismatch` or `not_completed` (no total, or conflicting totals). **Values are never changed and an invoice is never rejected.** On a mismatch the invoice is marked for review and lines that would close the gap at ×/÷10, 100 or 1000 get a suggestion (“₹35,000.00 may be ₹350.00”), never applied automatically. |
| 2 | Column boundaries for left-aligned headings | `DynamicSchemaGenerator._split_outside_value_block`: a boundary that cuts through a stack of **numeric** values, where the stack ends before the next heading, moves into the gap after it. Anything else is left alone. `TableReconstructor` flags a value lying more than 30% across a boundary (“its column is uncertain”) and the reason reaches the line's review reasons. |
| 3 | Three-decimal precision | Printed values keep up to 3 decimals through extraction, review, confirm request/response, purchase records, prints (`formatPrintedCurrency`, `printedMoney`) and the Excel audit export (`#,##0.00#`). Calculated amounts use `Decimal`, half-up, 3 decimals. |
| 4 | Numeric(14,3) migration | Proposal only: `MIGRATION_PROPOSAL_NUMERIC_14_3.md`. Not executed. |
| 5 | Fractional quantities | Investigation in `FRACTIONAL_QUANTITY_PROPOSAL.md`. **P0 implemented (approved):** a fractional quantity (2.5 kg) is no longer rounded silently. Confirmation is blocked with an explanation, the extracted reading stays visible for correction, and nothing is posted until the line is corrected or deselected. The backend rejects fractional quantity, paid or free units before any write. Whole-number behaviour is unchanged. P2 (fractional stock) is not implemented. |
| 6 | Free products | A confirmed 10+1 posts 11 received units and keeps `paid_quantity` 10, `free_quantity` 1, the printed rate and amount. No zero cost and no cost redistribution. A free line never overwrites an existing product's cost (a new product gets an unknown cost, NULL). Posting stock with free units needs explicit confirmation: the API returns 422 without `confirm_free_units`, and the UI shows a “Add to stock including free units” prompt. |
| 3a | Review edits keep 3 decimals | Editing a line's quantity or rate no longer re-rounds the line amount and invoice total to 2 decimals (`round3`). |
| 7 | Silent decimal error | Reproduced (quantity 2.50 → 250 and amount 350.00 → 35000 with arithmetic still agreeing). C2 now catches it, in a unit test and in the simulated dataset (TC15 perspective). |

## 2. Fix made during regression

The first dataset run showed one simulated case (TC13 blurry, headings unreadable) losing a line. The boundary refinement
had treated a run of **product-name words** as a value stack and moved a boundary across the table. The refinement now
uses numeric values only, which is what it was meant to do. A regression test was added
(`test_boundary_not_moved_by_product_name_text`). After the fix the case is identical to R1–R10.

## 3. Dataset comparison (executed)

| | Fixtures (32 / 160 lines) | Synthetic (17 / 121) | Simulated captures (81 / 416) |
|---|---|---|---|
| Lines found: baseline → R1–R10 → now | 155 → 155 → 155 | 114 → 114 → 114 | 317 → 321 → 321 |
| Fully correct | 145 → 145 → 145 | 104 → 102 → 102 | 250 → 243 → 243 |
| **Wrong and not flagged (silent)** | 0 → 0 → 0 | 0 → 0 → 0 | 12 → 1 → **0** |
| Wrong but flagged for review | 0 → 0 → 0 | 4 → 6 → 6 | 24 → 36 → 37 |
| Extra lines (flagged) | 0 → 0 → 0 | 0 → 0 → 0 | 22 (14) → 19 (18) → 19 (18) |

- The only case that changed from R1–R10 is TC15 decimal quantities (perspective). Its silent decimal error is now flagged by C2.
- The baseline → R1–R10 differences are explained in `PHASE3A_R1_R10_IMPLEMENTATION_REPORT.md` §4 (the silent quantity repair was removed and R8 recommends a retake).
- Per-dataset tables are in `after_phase3a_followup.md`.

**Four private real photos** were rerun locally; they are not stored in Git and no values are reproduced here. Every
extracted value and review flag is identical to R1–R10. Reconciliation reports `not_completed` on all four, because no
printed total is read reliably on these photos. That is the intended outcome when the total is not trustworthy.

## 4. Tests executed

| Suite | Result |
|---|---|
| Backend `pytest` (full) | **665 passed, 7 skipped, 0 failed** |
| New: `test_phase3a_followup.py` | 22 passed |
| New: `test_phase3a_confirm_precision_promotions.py` (incl. 5 P0 tests) | 16 passed |
| Frontend `tsc -b` | passed |
| Frontend `oxlint` | exit 0. Warnings only in files not touched by this work. |
| Frontend `vitest` | 13 files, 98 tests passed |
| Frontend `vite build` | passed |
| Browser: mobile capture | 25 / 25 |
| Browser: invoice metadata | 12 / 12. The test invoice's loose-weight line (2.5 kg) is now deselected before confirming; it used to be rounded silently to 3 |
| Browser: direct upload warning | 6 / 6 |
| Browser: `review_promotions_precision_check.cjs` (desktop + Pixel 7) | 16 / 16: total-check banner, ₹62.988 shown and stored, paid + free shown, prompt before posting, 11 units posted per confirmation with the printed cost, purchase total stored as 412.988, no horizontal overflow on the phone |
| Browser: `fractional_quantity_block_check.cjs` (desktop + Pixel 7) | 18 / 18: 2.5 kept in the field and marked, confirmation blocked with an explanation, no request and no stock while blocked, no bypass button, no overflow; posted after correction (desktop) or deselection (phone); whole-number lines unchanged |

All test values are generic. Values from the private invoice photos were removed from the tests and docs before committing.

## 5. Remaining risks

- C2 depends on the printed total being OCR-readable. On poor photos it reports `not_completed`, and then the silent-decimal error is not caught.
- A mismatch can also come from a missed or extra line, not only a decimal error. Suggestions are given only when one or two lines explain the gap at ×/÷10, 100 or 1000.
- Money is still stored as `Float` until the Numeric(14,3) migration is approved. Values round-trip correctly to 3 decimals, but SQL `SUM` adds binary doubles.
- Loose-weight lines (2.5 kg) must be re-expressed in whole units or deselected until fractional stock (P2) is approved.
- The boundary refinement acts only where numeric values form a clear block. Ambiguous layouts keep the previous behaviour plus the straddle flag.

## 6. Follow-up fixes (two pre-existing issues)

- **Editing a paid + free line:** changing its quantity or rate recalculated the amount from all received units
  (13 × ₹35 = ₹455 for "12 paid + 1 free"), and the free-unit breakdown was dropped. The free units now stay as
  printed, an edited quantity changes only the paid units, and the amount is paid units × rate (₹420). A quantity
  below the free units turns the line into an ordinary line. Tested in `invoiceReliability.test.ts` and in the
  phone pass of `review_promotions_precision_check.cjs` (now 17 checks).
- **Invoice status:** an invoice with any line still needing review is reported as `needs_review` (reason
  "1 of 3 lines needs review"), never `success`. The review screen does not use this field; it only changes the
  API value. Tested in `test_phase3a_followup.py`.
