# Phase 4 – Design and implementation roadmap (proposed, not implemented)

Status: **draft for approval [R].** Findings referenced from `BASELINE_AUDIT.md`; decisions [D-n] from `REQUIREMENTS.md` §6.

## 1. Principles
1. **Extend, never replace.** The OCR pipeline, P0 block, paid/free policy, total check and 3-dp purchase precision all stay.
2. **One unit model, one money policy, one quantity validator,** shared by every path.
3. **The backend is authoritative.** It computes and stores totals in `Decimal`. The frontend computes previews and display only.
4. **Validate, never round silently.** Convert only where a conversion is defined.

## 2. Canonical unit model (FU-1 … FU-5)

The existing OCR registry `CANONICAL_UNITS` (`backend/services/grocery_ocr/extraction/unit_normalizer.py`) becomes the single source. It gains a family and factor table (code → family, base, factor, fractional), and nothing is duplicated.

| Code | Display label | Family | Base | Factor | Fractional |
|---|---|---|---|---|---|
| KG | kg | MASS | G | 1000 | yes |
| G | g | MASS | G | 1 | yes |
| QTL / TON | quintal / tonne | MASS | G | 100000 / 1000000 | [D-1] |
| L | L | VOLUME | ML | 1000 | yes |
| ML | ml | VOLUME | ML | 1 | yes |
| PCS / NOS | pcs | COUNT | PCS | 1 | no |
| DOZ | dozen | COUNT | PCS | 12 | no |
| PKT | packet(s) | PACKAGE:PKT | PKT | 1 | no |
| BOX | box(es) | PACKAGE:BOX | BOX | 1 | no |
| PET | bottle(s) | PACKAGE:PET | PET | 1 | no |
| BAG, BOR, TIN, CAN, JAR, POUCH, CARTON, CASE, SET | as named | PACKAGE:<code> (each its own family) | itself | 1 | no |

- **Compatibility rule:** two units are compatible only when they're in the same family. MASS ↔ VOLUME is never compatible (no density). PACKAGE units are compatible only with themselves.
- **Product-specific conversions [D-4]:**
  - optional, user-confirmed per product (e.g. 1 BOX = 24 PCS for product X; 1 BAG = 25 KG for product Y);
  - stored per product;
  - used only for that product; never inferred from names or OCR.
- **Helpers (new, beside the normaliser):**
  - `unit_info(raw) → (code, label, family, factor, fractional)`;
  - `convert(qty, from, to, product_conversions=None) → Decimal`, raising `IncompatibleUnits` when the units can't be converted;
  - `validate_quantity(qty, unit) → Decimal` (> 0, ≤ 3 dp, fraction only if allowed).
- **`products.unit`** stays free text for compatibility, resolved through `unit_info`. Unknown text behaves as COUNT (whole), matching today's behaviour.
- **Every path uses the same model:**

  | Path | Use of the model |
  |---|---|
  | OCR | the normaliser already returns codes; the printed unit and factor are stored on the purchase line |
  | Voice-to-Bill | voice `CanonicalUnit` maps to codes (piece→PCS, packet→PKT, bottle→PET, dozen→DOZ); spoken "500 g" of a kg product converts to 0.5 |
  | Inventory | stock is held in the product's own unit |
  | Sales | quantities are validated with `validate_quantity` |
  | Product name matching | `product_matching._TO_BASE` is replaced by `convert()` (same factors) |
  | Frontend | `GET /api/v1/units` (read-only) supplies the registry; `CanonicalUnit` becomes a mapping onto it, not a separate list |

## 3. Quantity model (FQ-1 … FQ-9)
- **Storage:** `Numeric(12,3)` for stock, reorder level and line quantities [D-7].
- **Validation:** `validate_quantity` everywhere. P0 keeps its message for COUNT and PACKAGE units.
- **Stock movements become atomic conditional updates [D-8]:**
  - sales: `UPDATE products SET current_stock = current_stock - :q WHERE id=:id AND shop_id=:s AND current_stock >= :q`; zero rows affected gives an "insufficient stock" error;
  - purchases and invoices: `current_stock = current_stock + :q`;
  - everything stays in the existing single transaction with the header and line rows.
- **Manual stock edits** (`PUT /products`) still set an absolute value. **[R]** Optional later: a delta-based stock-adjustment endpoint with a reason.
- **Responses:** int fields become numbers that allow decimals (`float` from quantised `Decimal`). Whole values still serialise as `5`.

## 4. Purchase and sale data model

### 4.1 `purchase_items`

| Field | Essential? | Purpose |
|---|---|---|
| quantity (existing) | essential | received quantity in the **inventory unit** (paid + free, converted) |
| printed_quantity | essential | quantity as printed or entered, in the purchase unit |
| purchase_unit | essential | printed or entered unit code |
| inventory_unit | essential | product unit at the time of purchase (a snapshot; the product unit may change later) |
| conversion_factor | essential | purchase unit → inventory unit (1 when they're the same) |
| paid_quantity, free_quantity | essential | promo breakdown (today lost after confirmation) |
| purchase_price (existing) | essential | rate as printed |
| line_amount (existing) | essential | final line amount as printed |
| mrp, mrp_source (existing) | essential | |
| discount_amount (scheme + other) | optional [D-5] | as printed |
| taxable_amount | optional [D-5] | as printed |
| gst_rate, cgst_amount, sgst_amount, igst_amount | optional [D-5] | as printed |
| quantity_text (e.g. "10+1", "0/12") | optional | audit of the printed form |

### 4.2 `purchases` (optional)
printed_total, total_reconciliation_status, tax_total, discount_total.

### 4.3 `sale_items`

| Field | Essential? | Purpose |
|---|---|---|
| quantity, unit_price (existing) | essential | in the inventory unit |
| unit | essential | inventory unit snapshot (today the frontend hard-codes `'pcs'`) |
| line_total | essential | rounded paise amount (FM-3), so receipts and reports don't recompute it |
| entered_quantity, entered_unit | optional | e.g. "500 g" sold from a kg product |

All new columns are **nullable**: old rows and old clients stay valid.

## 5. Financial precision strategy (FM-1 … FM-8)

| Layer | Strategy |
|---|---|
| Backend calculations | `Decimal` only. One shared helper module with `money3()` (purchase, printed precision), `money2()` (sale lines and bills, paise), `qty3()`; half-up throughout. Reuses the logic of `_keep_printed_precision` from `services/invoice.py` (moved, not duplicated). Replaces float sums in `purchase.py` and `sale.py`, and `round(float, 2)` in `inventory_matcher.py` |
| Database | `Numeric(14,3)` money, `Numeric(12,3)` quantity [D-7]. On SQLite storage is REAL, but values are quantised on write and read. Aggregates are quantised when read |
| API serialisation | JSON numbers produced from quantised `Decimal` (`float(q)`), which is exact for ≤ 15 significant digits. No string money, so contracts are unchanged |
| Frontend calculations | previews only (review edits, cart, voice). The stored values come from the backend. Extend `src/utils/decimalCalc.ts` [D-9] (below) |
| Currency display | `formatCurrency` (2 dp) for sales; `formatPrintedCurrency` (3 dp when printed) for purchases. Receipts must format, never interpolate raw numbers (FM-5) |
| Tax | printed tax, discounts and GST are recorded as printed, never recomputed [D-5]. Sales carry no GST today (out of scope) |
| Rounding | round once, at the defined boundary (line, then bill). **Never round a rate or an intermediate product.** Prices are per inventory unit, so conversions change the quantity, not the rate (FM-4) |

### Why 2-dp intermediate rounding is unsuitable [C, probed]
- **Rates carry 3 decimals:** 12 × ₹7.143 = ₹85.716. Rounding the rate first gives 12 × ₹7.14 = ₹85.68, a ₹0.036 error on one line.
- **Per-gram rates:** ₹0.125/g × 2,500 g = ₹312.50 exact; ₹0.13/g × 2,500 g = ₹325.00, a ₹12.50 error.
- **Binary floats defeat `Math.round(x*100)/100` half-up:** `decimalMultiply(1.005, 1)` returns 1, not 1.01.
- **Examples:**
  - ₹0.10 + ₹0.20: float gives 0.30000000000000004; `Decimal('0.10') + Decimal('0.20')` = 0.30.
  - 2.500 kg × ₹120/kg: float 300 (exact by chance); `Decimal` 300.00. With 0.750 kg × ₹44.50: float 33.375; `Decimal` half-up = ₹33.38.

### `decimalCalc.ts` evaluation [C]
- It's unused, 2-dp only, and loses printed 3-dp values (12 × 5.249 → 62.99). Its half-up rounding is wrong for binary-boundary values.
- **[R] Extend it, don't replace:**
  - add a `places` parameter;
  - round via exponent shifting (`Number(Math.round(Number(x + 'e' + p)) + 'e-' + p)`), which handles 1.005 → 1.01;
  - make `invoiceReliability.round3`, `VoiceBillModal`, the cart and `salesService` line totals use it.
- No new dependency. `decimal.js` is an alternative only if you approve it [D-9].

## 6. Reports and exports
- **Receipts:**
  - `receiptGenerator.ts` formats line price and total with the formatter (fixes raw `0.30000000000000004`);
  - the receipt and print use the stored `sale_items.unit` and `line_total`.
- **Purchase record:** add the unit column; show paid + free when stored.
- **Inventory report:** `formatQuantity(stock, unit)`; optional valuation column (exact qty × cost, rounded for display).
- **Dashboard, insights, notifications:** quantised `Decimal` aggregates; `int()` casts removed.
- **Reorder engine:** whole-unit rounding stays for COUNT/PACKAGE; for MASS/VOLUME, round up to 0.5 of the unit [R].
- **Profit and valuation:** stay in the browser for now, but use stored line totals and exact products. **[R]** A backend endpoint is a later option.
- **Excel:** the invoice audit workbook is unchanged (already 3 dp). No other exports exist today; none added unless requested.

## 7. Concurrency (FQ-9)
See §3. Verified by a concurrency test that repeats the Phase 0 probe: two parallel sales must leave stock 8 of 10, and two parallel purchases must add both.

## 8. Compatibility
- Old clients sending integers keep working.
- JSON numbers are unchanged for whole values.
- Firestore offline sync (inactive for stock) accepts decimals.
- The invoice audit workbook is unchanged.

## 9. Local database safety and cleanup (NF-7, D-10, D-11)
- **Prevention:** implemented in workstream 9a. See `TEST_ISOLATION.md`: the fail-closed guard, `tests/conftest.py`, and the launcher `scripts/e2e/run.cjs` with dedicated ports, a port guard and no auto-started backend in test mode.
- **Telling test data from real data:**
  - test users always use `@example.com`, and test invoice numbers use `E2E-` or fixed fixtures (`BT-500`);
  - today **all** rows in the file match this (12/12 users, 0 non-test rows).
- **Cleanup [D-10, approved only as far as the backup]:**
  1. Stop all backends.
  2. Copy `backend/shoppulse.db` (plus `-wal` / `-shm`) to a backup.
  3. **Only with separate explicit approval:** delete the file (every row is test data; the next backend start recreates an empty schema), or delete the rows of `@example.com` owners in one transaction.
  4. Not executed.

## 10. Implementation roadmap (each workstream needs approval)

Every workstream ends with the full backend, Vitest, TypeScript, lint, build and browser suites green (NF-1).

| # | Workstream | Scope | Files likely to change | Depends on | Risks | Unit tests | Integration tests | Acceptance criteria |
|---|---|---|---|---|---|---|---|---|
| 9a (first) | Test isolation (NF-7) | conftest database override; browser-script dedicated port and guard | `backend/tests/conftest.py` (new), `tests/test_voice.py`, `scripts/e2e/*.cjs` | – | tests that relied on the default database | – | full suite passes on a temporary database; `shoppulse.db` modification time unchanged | NF-7 |
| 1 | Canonical unit architecture | registry families and factors, `unit_info`, `convert`, `validate_quantity`, `/units` endpoint; frontend mapping | `unit_normalizer.py`, new `services/units.py` (helpers only), `services/product_matching.py`, `api/routes/units.py`, `src/config/voiceLanguages.ts`, `src/api/units.ts` | 9a | OCR behaviour change if codes shift; mitigated by unchanged codes | every alias of the 4 vocabularies → one code; conversions; incompatible pairs | `/units` contract; OCR and product-matching suites unchanged | AT-FU-1/2/3 |
| 4 | Decimal-safe backend | money helpers; `purchase.py`, `sale.py`, `inventory_matcher.py`, dashboard, insights, notification aggregates | `services/{purchase,sale,inventory_matcher,dashboard,insights,notification,invoice}.py`, new `services/money.py` | 9a | changed totals in historical comparisons (new rows only) | money2/money3 half-up; 0.10 + 0.20; 33.375 → 33.38 | API probes: purchase and sale totals 0.30; golden responses | AT-FM-1/3/5 |
| 2 | Fractional inventory | unit-aware validation in schemas; Decimal stock movements; atomic updates; int casts removed | `schemas/{product,purchase,sale,invoice,voice,insights,search,dashboard}.py`, `services/{sale,purchase,invoice,inventory_matcher,insights,notification}.py` | 1, 4 | response type changes; P0 semantics | validator matrix (unit × value) | concurrency test (2 sales → 8); fractional sale and purchase on SQLite (works without migration) | AT-FQ-1/2/3/6/9 |
| 5 | Database migration | Alembic revision: Numeric types and new nullable columns; stamping procedure | `db/models/*.py`, `alembic/versions/<new>.py`, `main.py` (INCREMENTAL_COLUMNS) | 2, 3 design final | data conversion, unstamped databases | – | upgrade/downgrade/upgrade on a fixture database; rehearsal on a copy; PostgreSQL run (needs a container) | NF-2, NF-3 |
| 3 | Purchase and sale data model | persist printed qty and unit, factor, paid/free, optional tax fields; sale unit and line_total | `services/invoice.py`, `services/sale.py`, `schemas/{invoice,purchase,sale}.py`, `PurchaseRecordModal.tsx`, `PrintDocuments.tsx` | 5 | response size; old rows have NULLs | serialisation of NULL vs values | confirm 10+1 → stored 10/1/11; history API | AT-FQ-7, AT-FU-5, AT-FM-8 |
| 6 | Frontend quantity and money | `decimalCalc` extension; `formatQuantity`; `step` per unit; cart steps; validators | `src/utils/{decimalCalc,validators,invoiceReliability,formatCurrency}.ts`, `ProductFormFields.tsx`, `Sales.tsx`, `InvoiceScanner.tsx`, `VoiceBillModal.tsx`, `salesService.ts`, `receiptGenerator.ts`, `types/*` | 1, 2 | UI regressions at phone width | decimalCalc (1.005 → 1.01), formatQuantity | Vitest component checks | AT-FQ-8, NF-6 |
| 7 | OCR and Voice-to-Bill | lift P0 for measure units; voice unit conversion; scale feed (optional) | `InvoiceScanner.tsx`, `invoiceReliability.ts`, `services/voice_parser.py`, `inventory_matcher.py`, `VoiceBillModal.tsx` | 1, 2, 6 | P0 regression for count units | voice "500 g" → 0.5 kg | `/voice/process` → `/sales` 0.5 kg | AT-FQ-4/5 |
| 8 | Reports, exports, dashboard | receipts, prints, inventory report, reorder engine, analytics | `PrintDocuments.tsx`, `receiptGenerator.ts`, `reorderEngine.ts`, `analyticsService.ts`, `SalesOverview.tsx` | 3, 4, 6 | visual changes | receipt formatting, reorder rounding | print snapshots | AT-FM-5/6, AT-FQ-6 |
| 9b | Regression and acceptance | full suites, golden API contracts, all AT-* in the browser (desktop and phone) | `scripts/e2e/*` (new checks) | all | – | – | – | all requirements traced |

**Order:** 9a → 1 → 4 → 2 → (5 ∥ 3 design) → 5 → 3 → 6 → 7 → 8 → 9b.
- Workstream 4 fixes a live defect without a schema change.
- Workstream 2 works on SQLite before the migration, because of INTEGER affinity [C]. Workstream 5 makes the schema explicit and is required for PostgreSQL.
