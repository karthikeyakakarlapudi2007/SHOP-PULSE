# Phase 4 – Phase 0: Baseline audit (fractional inventory, units, financial precision)

Audit dates: 2026-11-19 (initial and completion). **Audit only:** no application source, schema or data was changed.
The only files created are the four documents in `docs/phase4/`.

Markers used in all four Phase 4 documents:

| Marker | Meaning |
|---|---|
| **[C]** | Confirmed: read in the code, or observed by running it. Runtime probes used in-memory or scratch SQLite databases, never `backend/shoppulse.db` (that file was only read, in read-only mode) |
| **[R]** | Recommendation |
| **[A]** | Assumption or inference, not verified by running |
| **[U]** | Unverified behaviour (needs a test before it is relied on) |
| **[D]** | Decision requiring your approval (collected in `REQUIREMENTS.md` §6) |

## 1. Git and branch [C]

| Item | Value |
|---|---|
| Branch | `claude/optimistic-ramanujan-jfmdxu` |
| HEAD | `6da7393`, synchronised with `origin/claude/optimistic-ramanujan-jfmdxu` |
| Working tree | clean apart from untracked `docs/phase4/` (these documents) |
| Merge base with main | `5483880` |
| `origin/main` | `3797201`. Its 2 extra commits are PR merges #32/#33 **with no file changes**, so there's no conflict |
| Commits not in main | 4 |
| Files changed vs main | **54** (68,138 insertions, 332 deletions) |

| Commit | Files | Content |
|---|---|---|
| `35c65cd` | 6 | real-photo validation harness (no photos) |
| `55bd649` | 7 | Phase 3A extraction baseline and plan |
| `77a73ed` | 43 | Phase 3A: OCR reliability (R1–R10), invoice total check, 3-dp precision, paid/free units, P0 whole-unit block |
| `6da7393` | 7 | promo-line edit fix, `needs_review` status fix |

The 54 files by area (A = added, M = modified):

| Area | Files |
|---|---|
| Invoice API and services (4) | M `backend/api/routes/document_prep.py`, M `backend/schemas/invoice.py`, M `backend/services/invoice.py`, A `backend/services/invoice_reconciliation.py` |
| Image preparation (3) | M `backend/services/document_prep/{document_detector,pipeline,quality}.py` |
| OCR extraction and Excel (11) | M `backend/services/grocery_ocr/excel/{workbook_generator,workbook_parser}.py`; M `extraction/{column_wise_extractor,dynamic_schema_generator,header_intelligence,header_recognizer,numeric_parser,price_extractor,table_reconstructor}.py`; M `pipeline/invoice_pipeline.py`; M `schemas/table.py` |
| Backend tests and evaluation (12) | A `test_ocr_reliability_r1_r10.py`, `test_phase3a_followup.py`, `test_phase3a_confirm_precision_promotions.py`, `test_validation_harness.py`, `validation_scoring.py`, `evaluate_extraction_baseline.py`, `fixtures/ground_truth/printed_values.json`; M `test_column_wise_extractor.py`, `test_document_prep_api.py`, `test_excel_first_processing.py`, `real_world_validation.py` |
| Frontend (7) | M `src/pages/InvoiceScanner.tsx`, `src/components/PrintDocuments.tsx`, `src/components/PurchaseRecordModal.tsx`, `src/utils/formatCurrency.ts`, `src/api/documentPrep.ts`; A `src/utils/invoiceReliability.ts`, `src/tests/invoiceReliability.test.ts` |
| Browser checks (5) | A `scripts/e2e/{direct_upload_warning_check,fractional_quantity_block_check,review_promotions_precision_check}.cjs`, `prepare_warning_assets.py`; M `invoice_metadata_check.cjs` |
| Docs and datasets (10) | A `docs/ocr-reliability/*` (proposals, reports, baseline and after JSON/MD) |
| Validation folder (3) | A `validation/real_invoices/{.gitignore,README.md,manifest.template.json}` |

The 43-file OCR implementation and both later fixes **are on this branch, and none of it is in main.**

## 2. Test baseline
- **[C] Last full runs were on `6da7393`:**
  - backend 667 passed, 7 skipped;
  - Vitest 102 passed;
  - TypeScript, lint (warnings only in untouched files) and build pass;
  - browser checks 25, 12, 6, 17 and 18 of 18.
- **Not re-run in Phase 0:** no source file has changed since.
- **[R]** Phase 1 starts by re-running everything to confirm the baseline.

## 3. Quantity architecture [C]

### 3.1 Storage

| Column | Declared type | Notes |
|---|---|---|
| `products.current_stock` | Integer NOT NULL, 0 | |
| `products.reorder_level` | Integer NULL, 0 | |
| `products.unit` | String, default `pcs` | free text, not validated |
| `purchase_items.quantity` | Integer NOT NULL | received units (paid + free); no unit stored |
| `sale_items.quantity` | Integer NOT NULL | no unit stored |

- **SQLite already stores fractions:** an INTEGER column stores 2.5 as REAL, and SQLAlchemy `Integer` reads back 2.5 (probed). On SQLite the whole-number limit is enforced only by the application.
- **[A]** PostgreSQL `integer` would reject 2.5.

### 3.2 Flow

```
Invoice OCR (Decimal 3 dp) → extract API (float) → review (P0 blocks fractions) → /invoices/confirm
  (whole-units validator) → services/invoice.py qty = int(...) → purchase_items.quantity → current_stock += qty
Manual purchase  → POST /purchases (int) → current_stock += qty
Sales cart (±1)  → POST /sales (int) → stock check → current_stock -= qty
Voice "0.5 kg"   → /voice/process (0.5 accepted) → cart → POST /sales → 422
Dashboard/insights/notifications → SUM(sale_items.quantity), int(...) casts, int response fields
```

### 3.3 Rejected, rounded or truncated

| Place | Behaviour |
|---|---|
| `schemas/product.py` (current_stock, reorder_level) | 422 (probed: 2.5 kg) |
| `schemas/purchase.py`, `schemas/sale.py` | 422 (probed: 2.5 kg, 0.5 kg) |
| `schemas/invoice.py` `whole_units` (P0) | 422 with a clear message (probed) |
| `services/invoice.py` confirm `qty = int(item.quantity)` | truncation (unreachable today) |
| `services/inventory_matcher.py` `int(current_stock)` | truncation (voice stock check) |
| `services/insights.py`, `services/notification.py` `int(...)` | truncation in reports and alerts |
| int response fields in `schemas/insights.py`, `search.py`, `voice.py`, `dashboard.py`, `product.py` | **[U]** a fractional value would fail response validation |
| `src/utils/validators.ts`, `ProductFormFields.tsx` (`step="1"`) | whole numbers only |
| `InvoiceScanner.tsx` | P0 block; `step="1"` |
| `src/services/salesService.ts` `mapBackendSaleToFrontend` | sale line **unit hard-coded `'pcs'`** |
| `src/utils/reorderEngine.ts` | `Math.ceil(deficit/5)*5`, `Math.floor(reorder/2)` |
| `src/pages/Sales.tsx` | cart steps ±1 |

## 4. Unit architecture [C]

| Vocabulary | Units | Conversions |
|---|---|---|
| OCR `unit_normalizer.CANONICAL_UNITS` | PCS, NOS, DOZ, SET, KG, G, QTL, TON, L, ML, BAG, BOR, PKT, BOX, PET (bottle), TIN, CAN, JAR, POUCH, CARTON, CASE | none, by design |
| `product_matching._UNIT_ALIASES` / `_TO_BASE` | kg, g, l, ml | kg→g, l→ml ×1000 (name matching only) |
| Frontend `CanonicalUnit` (`config/voiceLanguages.ts`) | kg, g, L, ml, piece, packet, box, bottle, dozen | none |
| `products.unit`, confirm `unit` | free text | none |

- **Compatibility:** nothing checks that units are compatible. A `bag` line adds to a `kg` product as a plain number.
- **Dozen:** "dozen" becomes the number 12 in the voice parsers; that's number parsing, not unit conversion.
- **Weighing scale:** `scaleService.ts` (3-dp weights) is used only by `deviceSimulator.ts`.

## 5. Financial precision [C]

### 5.1 Storage and computation
- **Columns:** all 9 money columns are `Float`. Tax, GST and discounts are not persisted.

| Value | Where | Arithmetic | Rounding |
|---|---|---|---|
| Invoice lines and total | `services/invoice.py` | Decimal | half-up, 3 dp |
| Grand-total check | `invoice_reconciliation.py` | Decimal | tolerance max(₹1, 0.1%) |
| Manual purchase total | `services/purchase.py` | float | **none** |
| Sale total | `services/sale.py` | float | **none** |
| Voice bill | `services/inventory_matcher.py` | float | `round(x, 2)`: binary half-even-like (`round(2.675, 2)` = 2.67) |
| Voice bill edits | `VoiceBillModal.tsx` | number | `Math.round(x*100)/100` |
| Sale line total | `salesService.ts` mapping | number qty × price, unrounded | – |
| Dashboard, insights, notifications | SQL `SUM` of REAL | float | `round(…, 2)` in insights |
| Revenue, profit, average bill, valuation | `analyticsService.ts`, `salesService.ts`, `useSales.ts` (browser only) | number | `Math.round` to rupees |

### 5.2 Probe results (executed 2026-11-19)
- **Stored float noise:** `POST /purchases` 1 × ₹0.10 + 1 × ₹0.20 → stored and returned `0.30000000000000004`. `POST /sales` 3 × ₹0.10 → the same.
- **Raw SQLite sums:** `SUM` of 0.1 + 0.2 (REAL, NUMERIC or TEXT columns) → `0.30000000000000004`. A `SUM` of ten 0.1 values gave 1.0, which shows only that SQLite compensates in some cases, **not** that sums are safe.
- **SQLAlchemy `Numeric(…, 3)` on SQLite:** stored as REAL; the app reads `Decimal('0.300')` because of quantisation on read.
- **`decimalCalc.ts`** (unused, 2 dp):
  - `decimalAdd(0.1, 0.2)` = 0.3;
  - `decimalMultiply(2.5, 120)` = 300;
  - `decimalMultiply(0.75, 44.5)` = 33.38;
  - **`decimalMultiply(1.005, 1)` = 1 (half-up expects 1.01)**;
  - `decimalMultiply(12, 5.249)` = 62.99 (the printed 62.988 is lost).
- **Rounding a rate before multiplying:**
  - 12 × round2(7.143) = 85.68 vs exact 85.716;
  - a per-gram rate of ₹0.125 rounded to 0.13 gives 2,500 g → ₹325 vs exact ₹312.50.
- **Python `Decimal`:** 0.10 + 0.20 = 0.30; 2.500 × 120 = 300.00; 0.750 × 44.50 → 33.38 half-up.

## 6. Reports, exports and display [C]

| Output | Implementation | Quantity | Money |
|---|---|---|---|
| Sale receipt (print) | `PrintDocuments.SaleReceiptDocument` | as stored, unit shown only if ≠ pcs, but the unit is always `'pcs'` from the mapping | `formatCurrency` 2 dp |
| WhatsApp receipt text | `receiptGenerator.ts` | `String(quantity)` | **line price and total printed raw** (`₹${item.total}`): 3 × ₹0.10 prints `₹0.30000000000000004`; totals use `toFixed(2)` |
| Purchase record (print and modal) | `PurchaseRecordDocument`, `PurchaseRecordModal` | as stored, no unit column | `formatPrintedCurrency` (3 dp when printed) |
| Inventory report (print) | `InventoryReportDocument` | `{stock} {unit}` as stored | 2 dp; no valuation column |
| Sales report (print) | `SalesReportDocument` | `name × qty` | 2 dp; totals from browser sums |
| PDF | browser print → "Save as PDF" (`usePrint.ts`); no PDF library | – | – |
| Excel | only the invoice audit workbook (`/invoices/{id}/excel`) | `#,##0.000` | `#,##0.00#` |
| Inventory, purchase or sales CSV/Excel export | **none exists** | – | – |
| Dashboard summary | backend `SUM(sales.total_amount)`; `SalesOverview` `Math.round`, `toFixed(1)` k/L/Cr | – | display rounding |
| Profit | browser only (`analyticsService.ts`): revenue − cost × qty, cost falling back to 75% of the selling price | – | rupees |
| Stock valuation ("blocked capital") | browser only: `Math.round(stock × cost)` | – | rupees |
| Low stock / out of stock | backend `current_stock <= reorder_level`; frontend `inventoryService`, `alertService`, `reorderEngine` | comparisons are fraction-safe | – |
| Reorder suggestion | `reorderEngine.ts` | rounded up to 5 whole units | – |

## 7. Inventory consistency and concurrency [C]
- **Transactions:** purchase, sale and invoice confirmation each write the header, the lines and the stock change in **one transaction** (`db.commit()` once; `db.rollback()` on error). Records and stock cannot diverge through a partial failure.
- **Lost updates:** stock is read with a plain `SELECT`, changed in Python and written back as an absolute value. **Probed:** two concurrent sales of 1 unit from stock 10, through the real `services.sale.create_sale` on a scratch SQLite file in WAL mode, recorded 2 sales and left **stock 9 instead of 8.** One update was lost silently.
- **Why it happens on SQLite:** Python's `sqlite3` starts the transaction only at the first write, so the read is not protected.
- **Same pattern elsewhere:**
  - `services/purchase.py` and the invoice confirm (`+=`) **[A]** have the same exposure;
  - product edits through `PUT /products` set an absolute stock value **[A]**;
  - two concurrent invoice confirmations creating the same new product may create duplicates **[A]**.
- **Atomic updates are possible [R]:** `UPDATE products SET current_stock = current_stock - :q WHERE id = :id AND shop_id = :s AND current_stock >= :q`, checking the affected row count. Alternatives: `BEGIN IMMEDIATE` (SQLite) or `SELECT … FOR UPDATE` (PostgreSQL).

## 8. Purchase and sale data-model gaps [C]
- **`purchase_items`** stores only quantity (received), purchase_price, line_amount, mrp and mrp_source. It does **not** store the printed quantity, purchase unit, inventory unit, conversion factor, paid and free quantities, discount, taxable amount, GST rate or amounts.
  - The paid/free breakdown is validated at confirmation and returned once in `promotional_lines`, then lost.
- **`purchases`** has no printed grand total, tax totals or reconciliation status.
- **`sale_items`** has no unit and no stored line total (the browser recomputes it).

## 9. Local database `backend/shoppulse.db` [C]
- **Contents:** 12 users, all `@example.com`, created 2026-11-18 17:43–18:00; 12 shops, 18 products, 4 suppliers, 10 purchases, 50 purchase lines, 10 notifications, 4 notification preferences, 0 sales. **Every row belongs to a test account; no non-test user exists.**
- **Origin:** browser checks of 2026-11-18. An older backend started without `DATABASE_URL` held port 8000; the new throwaway backend failed to bind (`address already in use`); the scripts wrote through the old one.
- **Mechanism (established in workstream 9a, see `TEST_ISOLATION.md` §1):** `vite.config.ts` auto-starts `backend/main.py` on port 8000 whenever Vite, **including Vitest**, starts with nothing on that port. Without `DATABASE_URL`, that backend uses this file.
- **Results unaffected:** the results behind `77a73ed` and `6da7393` came from later runs whose backend bound correctly to throwaway databases.
- **Now:** no process listens on 8000 or 5173, and no process has the file open. Last modified 2026-11-18 18:05:22. Later full test runs (2026-11-19) did not modify it.
- **What could write to it:**
  - any backend started without `DATABASE_URL`;
  - importing `main` runs `init_db_schema()` (create missing tables and columns) on the default database, and every test module imports `main`;
  - `tests/test_voice.py` calls `/voice/process` with the real `get_db` (reads the default database);
  - the browser scripts write through whatever answers on `API_URL` (default `http://127.0.0.1:8000`).
- **Not modified or deleted.** Prevention and cleanup recommendations: `DESIGN.md` §9.
