# Phase 3A – OCR reliability: baseline, root causes and implementation plan

**Status: analysis complete, no product code changed. Waiting for approval before implementation (Phase 7).**

All numbers below come from runs executed on 2026-11-17 on **repository fixtures, synthetic pages and
simulated phone captures**. None of them is real-world accuracy. They are never combined into one number.

Reproduce:
```
cd backend && .venv/bin/python tests/evaluate_extraction_baseline.py --cache /tmp/p3a \
    --json ../docs/ocr-reliability/baseline_phase3a.json --md ../docs/ocr-reliability/baseline_phase3a.md
```
The tool calls the same function as `POST /api/v1/invoices/extract` (`_extract_invoice_with_new_pipeline`),
offline (MRP lookup disabled, no inventory). Prepared PDFs are cached so before/after runs read identical inputs.

## Phase 0 – project state

| Check | Result |
|---|---|
| Branch | `claude/optimistic-ramanujan-jfmdxu` |
| Phase 1 commit `5483880` in `main` | yes (PR #33, main = `3797201`) |
| Harness commit `35c65cd` in `main` | **no** – it is on the working branch only (one commit ahead of main), nothing lost |
| Image preparation (`services/document_prep`), HEIC, PDF builder | present |
| OCR language | English only (`eng`) |

## Phase 1 – datasets and a correction to the test data

| Dataset | What it is | Cases / lines |
|---|---|---|
| Repository fixtures | 32 files in `tests/fixtures/ground_truth/invoices` (digital PDFs, renders, one noisy photo-like render, one text file) uploaded as-is | 32 / 160 |
| Synthetic pages | `tests/doc_prep_dataset.py`, exact header and items, prepared → PDF | 17 / 121 |
| Simulated phone captures | 10 fixture layouts × 8 camera conditions + 1 two-page case, prepared → PDF | 81 / 416 |

**`ground_truth.json` does not match the printed pages for several fixtures** (verified against the PDF
text layer and by viewing every image):
- TC01–TC12 print invoice numbers `SBW-41NN`, but `ground_truth.json` records `BAL-2024-0NN`.
- TC04 has no MRP or unit column, but `ground_truth.json` records both.
- TC06 and TC08 list different products or values from the printed page.
- TC09 prints no unit column, and its discount percentages differ.
- TC10's header differs from the file.
- TC13 rows 9–13, its header and its grand total differ from the page.
- TC14 prints two items.

Scored against the old file, correct extractions showed up as "silent errors" (for example all of TC08).
The verified values are in `tests/fixtures/ground_truth/printed_values.json`; `ground_truth.json` is unchanged
because existing tests use it. The discrepancies are listed inside the new file.

## Phase 1 – baseline (before any change)

A line is **fully correct** only when product name, quantity, rate and amount are all correct (a rate or
amount the invoice does not print is not required). Units are compared in the product's canonical vocabulary
(`btl` = `PET`, `KGS` = `KG`); that is naming, not quantity conversion.

| Field (evaluated / correct) | Fixtures | Synthetic | Simulated |
|---|---|---|---|
| Lines fully correct | **145 / 160** | **104 / 121** | **250 / 416** |
| Lines found | 155 | 114 | 317 |
| Product name | 145 / 160 | 107 / 121 | 267 / 416 |
| Quantity | 155 / 160 | 112 / 121 | 290 / 416 |
| Unit | 109 / 118 | 110 / 121 | 109 / 204 |
| Purchase rate | 152 / 157 (+3 calculated, not printed) | 112 / 121 | 287 / 416 |
| MRP | 95 / 100 | 114 / 121 | 120 / 196 |
| Amount | 155 / 160 | 114 / 121 | 303 / 416 |
| **Wrong qty/rate/amount shown WITHOUT review flag** | **0** | **0** (4 wrong, all flagged) | **12** (36 wrong, 24 flagged) |
| Non-invoice lines added as items (unflagged) | 0 | 0 | 22 (8) |
| Decimal-point corruption (10^k) | 0 | 0 | 14 values |
| Supplier correct / partial / wrong / missed | 22 / 9 / 0 / 0 | 14 / 0 / 3 / 0 | 52 / 7 / 11 / 10 |
| Invoice number correct / missed | 29 / 2 | 15 / 2 | 57 / 23 |
| Invoice date correct / missed / wrong | 30 / 1 / 0 | 15 / 2 / 0 | 62 / 14 / 4 |
| Median extraction time | 1.4 s | 3.1 s | 2.7 s (+ 5.9 s preparation) |

Simulated captures by condition: fully correct lines / silent financial errors

| Upside down | Sideways | Shadow | Tilted | Perspective | Low light | Blurry | Small text | 2-page |
|---|---|---|---|---|---|---|---|---|
| 48/51 · 0 | 46/51 · 0 | 46/51 · 0 | 37/51 · 0 | 31/51 · 2 | 30/51 · 1 | 4/51 · 9 | 0/51 · 0 | 8/8 · 0 |

## Phase 2 – root causes (reproduced, not assumed)

| # | Problem | Reproduced? | Root cause |
|---|---|---|---|
| R1 | Wrong quantity/rate shown as verified | **yes – 11 of 12 silent errors** (10 confirmed by re-running the pipeline) | When OCR misses quantity or rate, `services/invoice.py` calculates it (qty = amount ÷ rate, rate = amount ÷ qty). The `verified` check then uses the calculated value, which always agrees, so `needs_review` is false. Example: CHANA rate "2,760.00" read as 276000, so qty is calculated as **0.01** and the line is "verified". On TC13 blurry the S.No column was read as the rate (6, 7, 8…), giving calculated quantities of 293, 960 and so on. Calculated values are not marked, and they use float `round()` (differs from half-up by ₹0.01; for example 0.09 ÷ 2 gives 0.04). |
| R2 | Decimal point lost in qty and amount consistently | yes – 1 silent (TC15 perspective: 2.50 → 250, 350.00 → 35000) | Line arithmetic still agrees. The printed grand total (1,210) was read but is discarded whenever line items exist (`invoice_total = sum of lines`). |
| R3 | 58.75 → 58575 class (decimal point read as a digit or dropped) | 14 values in simulated captures (×100 shifts) | OCR reads "245.00" as "24500". Where the printed amount reconciles, the existing suggestion already offers 245.00 (TC17 ×3, flagged). Other cases are flagged by R1 or not at all (MRP does not take part in the arithmetic). |
| R4 | Product names replaced, pack size dropped | yes – "Fortune Besan 500g" → "Fortune Besan" (TC20, TC31, TC32) | `GroceryOCRConfig.ai_provider = "mock"` is the **production default**, so a hard-coded test provider (`MockAIProvider`) rewrites names. For example any "…BESAN…" becomes "Fortune Besan" and the pack size is removed, which would merge a 500 g and a 1 kg SKU. |
| R5 | Product names truncated to one word | yes – TC23 ("Everest"), TC14 ("Metal", "Tool") | Table headings that are not in the synonym list ("Spice Name", "Name of Product / Service") are split into one column per word. The product column then becomes one narrow word. The older detector merges such fragments, but the production `DynamicSchemaGenerator` does not. |
| R6 | Photo uploaded through "Upload file" gives no items | yes – TC03 photo: **0/5 lines** as uploaded, **5/5** when prepared | File mode sends images straight to OCR, bypassing preparation. The old preprocessor fails on this photo. |
| R7 | Supplier includes "TAX INVOICE" | yes – 9 fixtures, 7 simulated (partial) | The title on the right is on the same text line as the supplier name, and `extract_metadata` keeps the whole line. |
| R8 | Supplier words in the wrong order ("TRADERS LAKSHMI WHOLESALE SRI") | yes – 2 synthetic | Large title words come back as one-word lines sorted by height. On a slightly tilted page the right-hand words come first, and `_merge_title_fragments` joins them in that order. |
| R9 | Invoice number missed when OCR garbles "Invoice" | yes – TC13 ("¥eice" on a separate line), synthetic 06 ("'veice No:") | `_INVNO_RE` needs `invoice/inv/bill/voucher` (or the clipped `nvoice/voice`) before "No". In 12 of 13 simulated misses the label text is not in the OCR output at all, so nothing can be fixed there. |
| R10 | Quantity "12" read as 128/124 | yes – 2 synthetic (flagged) | The cell border right after a right-aligned number is read as a digit. |
| – | Incorrect table-column alignment | partly – R5, R1 (S.No read as rate on blurry TC13) | – |
| – | Product descriptions merged or split | merged rows only on degraded captures ("Chana 50 KG Fortune Be") | Capture quality; no layout rule found to fix safely. |
| – | Headings read as products | 1 summary row as an item ("Total Quantity 110") on a blurry capture | Same as R1 (a calculated value made it look verified). |

Not reproduced on these datasets: PDF processing defects (all PDFs are read from the text layer correctly) and
units turned into quantities.

## Phase 5 – image preparation review

- **Works well:** upside down 48/51, sideways 46/51 and shadow 46/51 lines.
- **Weaker:** tilted 37/51, perspective 31/51 and low light 30/51. The losses come from OCR misreads (decimals, character confusion), not from geometry: every page was turned upright, and no wrong rotation occurred.
- **Not recoverable:** blurry 4/51 and small text 0/51. A retake was advised for 18 of 20 such captures; it was missed on TC13 blurry and one other blurry capture.
- **No change proposed to preparation algorithms:** there is no evidence of a fixable algorithm fault. Tuning the retake threshold on 2 misses would be guesswork without real photos.
- **Fine text and decimals:** decimal loss (R3) happens on perspective, low-light and blurry captures. It is an OCR read error, and preparation cannot reliably prevent it. It is handled at the validation stage (R1–R3) instead.
- **Original-image fallback** stays as it is.

## Phase 6 – prioritized implementation plan (approval required)

### CRITICAL

**C1. Never present a calculated quantity or rate as read and verified** (R1, R2 partly, R10)
- Evidence: 11 of 12 silent financial errors (simulated); fixtures TC04 (3 calculated rates) and TC30 (4 calculated quantities, Qty column not read by OCR) are correct today only by luck of the arithmetic.
- Solution:
  - Keep the calculated value, so the user doesn't have to type it.
  - Record it in a new additive item field `derived_fields` (e.g. `["quantity"]`).
  - Add the issue "Quantity not read from the invoice – calculated as ₹X ÷ ₹Y. Please check", and set `needs_review`.
  - Base `verified` only on values that were read.
  - Do the calculation with `Decimal` and half-up rounding to 2 places (rate) or 3 places (quantity).
  - Review screen: show a "calculated" tag on such cells.
- Files: `backend/services/invoice.py`, `backend/schemas/invoice.py` (optional field, default `[]`), `src/pages/InvoiceScanner.tsx`, and the item type in `src/`.
- Expected: simulated silent errors 12 → about 1 (the TC15 perspective case is C2's). The 8 unflagged non-invoice lines should mostly become flagged (unverified).
- Regression risk:
  - More review flags on layouts that print no Qty or Rate column (TC04, TC30). This is intended.
  - Tests asserting `needs_review == False` or `status == "success"` for such lines may need updating, and each one will be reported.
  - The confirm endpoint, inventory and duplicate detection are unaffected.
- Tests:
  - Unit tests: quantity calculated → flagged + `derived_fields`; rate calculated → flagged; read values → not flagged; Decimal rounding (0.09 ÷ 2 → 0.05).
  - API test on TC04/TC30; vitest for the tag.
  - Baseline rerun: silent count must fall and fully-correct counts must not drop.

**C2. Check line items against the printed grand total** (R2)
- Evidence: TC15 perspective, where the total was read as 1,210 against 101,200 summed from the lines.
- The total reader is unreliable today. On TC13 it picks "Total Tax 215.76" and on another capture "3.0", so without care this would raise false alarms (seen on 2 correct invoices).
- Solution:
  - Only compare when the label is Grand Total, Net Amount or Amount Payable (not a bare "Total" or "Total Tax").
  - Compare only on single-page documents.
  - On a mismatch, add an invoice-level warning showing both numbers, and set status `needs_review`.
  - Where exactly one line's amount ×/÷ 10^k reconciles, add a suggestion on that line, never applied automatically.
  - Return the printed total in a new additive field `printed_invoice_total`.
- Files: `backend/services/invoice.py` (`extract_metadata`, response), `backend/schemas/invoice.py`, `src/pages/InvoiceScanner.tsx` (warning banner).
- Risk:
  - False warnings when totals include round-off, freight or tax lines; mitigated by warning only, never changing values.
  - The reconciliation rate will be reported per dataset.
- Tests: label priority (Grand Total beats Total Tax); match → no warning; ×100 line → warning + suggestion; round-off line tolerated; dataset rerun.

### HIGH

**H1. Turn off the mock AI provider in production** (R4)
- Evidence: TC20, TC31, TC32 lose "500g", and every "…besan…" product is renamed.
- Solution: default `ai_provider` becomes `"disabled"`. Tests that use the mock already pass `MockAIProvider` explicitly; 3 tests that build `AIInterpretationService()` with defaults will pass it explicitly.
- Files: `backend/services/grocery_ocr/config.py` (one line in the protected OCR package; justified as a configuration fix, not an engine change), `backend/tests/test_ai_assisted_validation.py`.
- Expected: fixture product names 145 → 148/160.
- Risk:
  - Any behaviour that relied on mock renames ("Ttaa Slat" → "Tata Salt") disappears. Those were hard-coded test rules, not real intelligence.
  - The existing Gemini/Groq switch is unchanged.
- Tests: pipeline keeps "Fortune Besan 500g"; the mock is still used when configured; full AI test suite.

**H2. Keep multi-word table headings together** (R5)
- Evidence: TC23 (4 names truncated) and TC14 (2 names truncated).
- Solution, in `DynamicSchemaGenerator.generate_schema`:
  - Merge contiguous unknown heading words (gap within the existing word-gap rule) into one phrase.
  - Merge unknown fragments directly adjacent to the product column (the logic the older detector already has).
  - If no product column exists, classify a phrase built around "name", "description" or "particulars" ("Spice Name", "Name of Product / Service") as the product column.
  - No layout is hard-coded.
- Files: `backend/services/grocery_ocr/extraction/dynamic_schema_generator.py`; tests in `test_invoice_table_reconstruction.py` / `test_header_intelligence_and_schema.py`.
- Expected: fixture names +6 (TC23 0/4 → 4/4, TC14 0/2 → 2/2).
- Risk: column boundaries change for any invoice with unknown heading words. The full fixture, synthetic and simulated rerun must show no line getting worse.
- Tests: "Spice Name" and "Name of Product / Service" headings; header with a genuinely separate unknown numeric column stays separate; all existing table tests.

**H3. Prepare photos sent through "Upload file"** (R6)
- Evidence: TC03 photo 0/5 → 5/5 when prepared.
- Solution:
  - In file mode, send image files (JPG, PNG, WEBP, HEIC) through the existing preparation + extraction API.
  - Keep the original-photo fallback and the existing error handling.
  - PDFs and text files are unchanged.
  - Measure all 21 fixture images both ways before switching.
- Files: `src/pages/InvoiceScanner.tsx`; the e2e harness check.
- Risk:
  - About 6 s more per photo.
  - A clean digital PNG could read differently after preparation. The earlier measurement found no fixture worse, and it will be re-measured; if any image is worse, this item is not applied.
- Tests: vitest routing test; mobile e2e (`mobile_capture_check.cjs`); dataset comparison.

### MEDIUM

**M1. Remove "TAX INVOICE" and similar titles from the supplier line** (R7)
- Strip a leading or trailing document title (tax invoice, invoice, bill of supply, cash memo, original for recipient) from the supplier candidate.
- File: `services/invoice.py`.
- Expected: fixtures partial 9 → 0.
- Tests: title on the same line, title alone, supplier names containing "Invoice" mid-name stay intact.

**M2. Join one-word title lines left to right** (R8)
- Before metadata extraction, put one-word lines whose vertical extents overlap into x order. All of them stay; only the order changes.
- File: `services/grocery_ocr/pipeline/invoice_pipeline.py` (the lines passed to `extract_metadata` only).
- Tests: tilted title fixture.

**M3. Invoice number when the "Invoice" label is garbled** (R9)
- Accept OCR variants of the label (`…oice`, `…eice`, a word within edit distance 2 of "invoice") before "No".
- Accept an orphan "No.:" label in the header block only when:
  - the preceding word is not another known label (Ph, Challan, PO, GSTIN, Acc…);
  - the value contains a digit;
  - the value is not a phone number, date or GSTIN.
- Return such values with confidence 60, and show them on the review screen as "Detected – please check" (the UI ignores confidence today).
- Files: `services/invoice.py`, `src/utils/invoiceMetadata.ts`, `src/pages/InvoiceScanner.tsx`.
- Expected: TC13 and synthetic 06 recovered. Most simulated misses are not recoverable (the label is absent).
- Risk: a wrong number from the "No.:" fallback; mitigated by the check marker and by duplicate detection still using only confirmed values.

**M4. Suggest the quantity when a border is read as a digit** (R10)
- When the quantity × rate mismatch disappears by removing one trailing or leading character from the read quantity, offer that quantity as a suggestion, never applied (same pattern as the existing rate suggestion).
- File: `services/invoice.py`.

### LOW
- **L1.** Pack-size character confusion in names ("Skg", "Sg", "59"). Only "S" → "5" directly before a unit is safe; "59" is ambiguous. Proposed only if approved.
- **L2.** Show the printed unit next to the canonical one (currently "btl" is shown as "pet").
- **L3.** Performance: preparation median 5.9 s (max 18.7 s) per capture; extraction 1.4–3.1 s. No change proposed.

### Not proposed
- No OCR engine change.
- No new OCR service or dependency.
- No change to image-preparation algorithms.
- No dictionary-based correction of product names ("Sait" → "Salt"), because that could create false matches.
- No change to `ground_truth.json` without your decision.

## Tests that still need real photographs
All accuracy figures above, especially:
- decimal loss under real low light and blur;
- thermal and dot-matrix receipts;
- handwritten amounts;
- creased paper;
- real lens perspective;
- the retake threshold;
- the extra time from H3 on real phones.
