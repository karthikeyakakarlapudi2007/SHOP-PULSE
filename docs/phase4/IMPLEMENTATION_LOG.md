# Phase 4 – Implementation log

Each entry records the scope, the files changed and the **executed** verification. Nothing is committed until approved.

## 2026-11-19 – Phase 1 requirements approved
- Decisions D-1 … D-11 approved as listed in `REQUIREMENTS.md` §6.
- D-7: the migration still needs its own approval gate.
- D-10: back up first; no deletion without separate approval.

## 2026-11-19 – Workstream 9a: test database isolation (implemented, uncommitted)

Design and usage: `TEST_ISOLATION.md`.

### Files

| File | Change |
|---|---|
| `backend/core/db_safety.py` | **new**: test-mode detection and fail-closed database URL guard |
| `backend/db/session.py` | calls the guard before the engine is created (no-op outside test mode) |
| `backend/tests/conftest.py` | **new**: test mode plus a temporary SQLite `DATABASE_URL` before `main` is imported; asserts the engine; removes the temp directory |
| `backend/tests/test_db_safety.py` | **new**: 20 unit and integration tests |
| `vite.config.ts` | proxy target from `SHOPPULSE_API_TARGET` (default 8000 unchanged); no auto-started backend in test mode **or under Vitest** |
| `src/tests/testIsolation.test.ts` | **new**: the auto-start plugin is absent under Vitest; proxy default kept |
| `scripts/e2e/run.cjs` | **new**: launcher with port guard, own backend, Vite and test database, and the protected-file check |
| `scripts/e2e/e2e_env.cjs` | **new**: shared target; refuses direct runs and development ports |
| `scripts/e2e/{mobile_capture,invoice_metadata,direct_upload_warning,review_promotions_precision,fractional_quantity_block}_check.cjs` | use the shared target instead of hard-coded 5173 / 8000 URLs (assertions unchanged) |
| `docs/phase4/TEST_ISOLATION.md`, `IMPLEMENTATION_LOG.md` | **new** |
| `docs/phase4/REQUIREMENTS.md`, `DESIGN.md` | decision status and cleanup wording updated |

Not changed: application behaviour, schema, data, OCR, Voice-to-Bill, financial logic, UI.

### Verification (executed)

| V-Model level | Test | Result |
|---|---|---|
| Unit | `tests/test_db_safety.py` URL selection, refusals, test-mode detection | 20 passed (includes the 3 integration tests below) |
| Integration | subprocess `import main`: test mode without `DATABASE_URL` | refused (`UnsafeTestDatabaseError`), protected file unchanged |
| Integration | subprocess with `DATABASE_URL=sqlite:///./shoppulse.db` in test mode | refused ("protected development database") |
| Integration | subprocess with a temporary database | starts; schema created in the temporary file only |
| Integration | `pytest --noconftest` (isolation bypassed), with no `DATABASE_URL` and with the dev database | both refused at collection; protected file unchanged |
| Integration | Vite with `SHOPPULSE_TEST_MODE=1` and nothing on port 8000 | no backend auto-started; port 8000 stayed free |
| System | full backend suite, run 1 | **687 passed, 7 skipped, 0 failed** |
| System | full backend suite, run 2 (repeat) | **687 passed, 7 skipped, 0 failed** |
| System | `node scripts/e2e/run.cjs` (all checks) | mobile capture 25/25, invoice metadata 12/12, direct upload 6/6, promotions and precision 17/17, fractional block 18/18 |
| Integration | Vitest auto-start: Vitest with `DATABASE_URL` set to a scratch file | **before the fix: a backend started** (scratch database created); after: none |
| System | TypeScript, lint, Vitest, production build (after the Vitest fix) | pass; lint exit 0 (warnings only in untouched files); **Vitest 104 passed, 14 files** |
| System | all browser checks again, after the Vitest fix | 25/25, 12/12, 6/6, 17/17, 18/18; protected file unchanged |
| Acceptance | `backend/shoppulse.db`, `-wal`, `-shm` fingerprint (SHA-256, size, modification time) before, after each backend run, after the bypass checks, and inside the launcher | **unchanged every time** |
| Acceptance | port guard: port 8765, then 5174, occupied by a dummy server | launcher stopped with exit 2 and a clear message; no check ran |
| Acceptance | `E2E_BACKEND_PORT=8000` | refused, exit 2 |
| Acceptance | check run directly / with `API_URL` on 8000 | refused, exit 2, before any request |
| Acceptance | leftovers | no test servers running; temporary directories removed |

Baseline before 9a: 667 backend tests. Now 687 (+20 new); no existing test changed.

### Notes
- **Vitest finding:** Vitest loads `vite.config.ts`, whose auto-start plugin launched `backend/main.py` on port 8000 during every Vitest run. It used `backend/shoppulse.db` when `DATABASE_URL` was unset. This is the most likely source of the stray port-8000 backend seen on 2026-11-18. Fixed and covered by a test.
- **Incident during 9a:** one Vitest run made before that fix opened `backend/shoppulse.db` through the auto-started backend. SQLite then removed the empty `-wal` and the `-shm` side files. `shoppulse.db` itself is unchanged (SHA-256 `63c44cad…639d`, 303,104 bytes, modified 2026-11-18 18:05:22). All later fingerprints use that state as the baseline.
- **Side files:** `backend/shoppulse.db-wal` (0 bytes) and `-shm` were created on 2026-11-19 06:49 by the read-only Phase 0 audit queries. The data is unchanged and the files were left in place.
- **Process clean-up:** one check process (the test-mode Vite on port 5175, started for the auto-start check) had to be stopped by its exact command line, because `setsid` forked. It was this task's own process.

## 2026-11-19 – Workstream 1: canonical unit registry (implemented, uncommitted)

Design, contract and limitations: `UNIT_REGISTRY.md`.

### Files

| File | Change |
|---|---|
| `backend/services/unit_registry.py` | **new**: the canonical registry (families, units, aliases, fraction rules), lookups, exact conversion, quantity validation, product-specific conversion objects |
| `backend/services/grocery_ocr/extraction/unit_normalizer.py` | the literal 72-alias table is replaced by the registry-derived `CANONICAL_UNITS` (same name, same codes) |
| `backend/services/product_matching.py` | its private alias and factor tables are replaced by registry lookups |
| `backend/schemas/units.py`, `backend/api/routes/units.py`, `backend/api/main.py` | **new** read-only, authenticated `GET /api/v1/units` |
| `backend/tests/test_unit_registry.py` | **new**: 108 tests |
| `src/api/units.ts`, `src/utils/unitRegistry.ts`, `src/hooks/useUnitRegistry.ts` | **new**: types, lookups, cached loader |
| `src/components/ProductFormFields.tsx` | unit suggestions from the registry (field stays free text) |
| `src/tests/unitRegistry.test.ts`, `src/tests/fixtures/unit_registry.json` | **new**: frontend tests; the fixture is checked against the live registry by a backend test |
| `scripts/e2e/unit_registry_check.cjs`, `scripts/e2e/harness/product-form.html`, `product_form.tsx`, `scripts/e2e/run.cjs` | **new** browser check (desktop and phone, registry available or down), registered in the launcher |
| `src/tests/testIsolation.test.ts` | lint fix (unsafe optional chaining), from workstream 9a |
| `docs/phase4/UNIT_REGISTRY.md`, this log | documentation |

Not changed: schema, data, money calculations, stock behaviour, OCR engine, Voice-to-Bill.

### Verification (executed)

| Level | Result |
|---|---|
| Unit and integration (backend) | `test_unit_registry.py` 108 passed |
| Unit (frontend) | `unitRegistry.test.ts` 7 passed |
| System | backend **795 passed, 7 skipped, 0 failed**; Vitest **111 passed** (15 files); TypeScript, lint (exit 0; warnings only in untouched files) and production build pass |
| System (browser, launcher) | mobile 25/25, metadata 12/12, direct upload 6/6, promotions 17/17, fractional 18/18, unit registry 16/16; `backend/shoppulse.db` unchanged |
| Regression (OCR datasets, in-memory DB) | every extracted item value, unit and header identical to the last recorded run; only `status` differs (23 cases) because of the earlier status fix |
| Protected database | SHA-256 `63c44cad…` unchanged before and after all runs |

### Notes
- **`unit_registry_check` was flaky at first, from the check itself:** it opened the page without a token, the anonymous 401 made the API client clear the token, and the check had set the token in between. Fixed by installing the token before the first load. It then passed 3 runs in a row.
- **Bug found by the tests and fixed before the report:** `ProductUnitConversion.create` passed a unit object to the lookup. `get_unit` now accepts a resolved `UnitDefinition`.

### Final verification before commit (2026-11-19)

| Check | Result |
|---|---|
| Product-matching investigation | the only new spelling is "kilos". Same sizes now match across spellings; two old cases where different sizes could merge (5 vs 10 kilos, 2.5 vs 25 kilos) are now blocked. Distinct brands and items at the same weight still don't match. 21 regression tests added (generated names) |
| `test_unit_registry.py` | 129 passed |
| Full backend suite | **816 passed, 7 skipped, 0 failed** (baseline 687; +129 registry tests) |
| Full Vitest suite (re-run after the `testIsolation` lint fix) | **111 passed, 15 files** (baseline 104; +7) |
| TypeScript, lint, production build | pass; lint exit 0, no warnings in workstream 1 files |
| Browser checks (launcher, isolated) | 25/25, 12/12, 6/6, 17/17, 18/18 (unchanged from baseline); unit registry 16/16 |
| Protected database | `shoppulse.db` SHA-256, size and modification time unchanged before and after all runs; no schema, model or migration file touched |
| Clean-up | no test servers running; two launcher temp folders kept from the earlier failed `unit_registry_check` runs were removed (test data only) |

## 2026-11-19 – Workstream 4: Decimal-safe backend money (implemented, uncommitted)

Audit: `DECIMAL_AUDIT.md`. Implementation and limitations: `DECIMAL_IMPLEMENTATION.md`. Decisions 1 to 4 approved.

| Area | Files |
|---|---|
| Money module (new) | `backend/services/money.py` (invoice helpers moved here) |
| Sales, purchases | `services/sale.py`, `services/purchase.py` |
| Voice | `services/inventory_matcher.py`, `schemas/voice.py` (optional `unit_price_exact`) |
| Reports | `services/insights.py`, `services/dashboard.py`, `services/notification.py` |
| Invoice and OCR | `services/invoice.py`, `services/mrp_lookup.py`, `services/invoice_reconciliation.py`, `grocery_ocr/financial/calculation_engine.py`, `grocery_ocr/extraction/numeric_parser.py`, `grocery_ocr/extraction/column_wise_extractor.py`, `grocery_ocr/excel/workbook_parser.py` |
| Tests (new) | `backend/tests/test_decimal_money.py` (34) |

| Verification | Result |
|---|---|
| Backend full suite | **850 passed, 7 skipped, 0 failed** (previously 816) |
| Vitest, TypeScript, lint, build | 111 passed (15 files); pass; exit 0 (the same 12 pre-existing warning files); pass |
| Browser checks (launcher) | 25/25, 12/12, 6/6, 17/17, 18/18, 16/16 |
| OCR dataset re-run | zero differences vs workstream 1 |
| `backend/shoppulse.db` | SHA-256, size and modification time unchanged; no schema, model or migration file changed; historical records not rewritten (covered by a test) |

## 2026-11-19 – Workstream 4 committed (`8acf29c`), then fractional inventory and atomic stock updates (uncommitted)

Report: `FRACTIONAL_INVENTORY.md`.

| Area | Files |
|---|---|
| New | `backend/services/stock.py` (unit-aware quantities, atomic updates), `backend/schemas/quantity.py`, `backend/tests/test_fractional_inventory.py` (31) |
| Schemas | `product.py`, `sale.py`, `purchase.py` (optional `unit`), `invoice.py` (unit required by the confirm service; fraction rule unit-aware), `voice.py`, `insights.py`, `dashboard.py`, `search.py` |
| Services | `product.py`, `sale.py`, `purchase.py`, `invoice.py`, `inventory_matcher.py`, `insights.py`, `notification.py`, `dashboard.py`, `unit_registry.py` (+ bar, sachet, roll, strip, tray, tube) |
| Routes | `api/routes/products.py` (validation errors → 400) |
| Tests updated to the approved rules | `test_inventory_crud_and_ocr_saving.py`, `test_invoice_flow_e2e.py`, `test_invoices.py`, `test_invoices_phase9.py`, `test_ocr_reliability_r1_r10.py`, `test_phase3a_confirm_precision_promotions.py`, `test_phase3a_followup.py`, `test_unit_registry.py`; frontend fixture `src/tests/fixtures/unit_registry.json`; `scripts/e2e/fractional_quantity_block_check.cjs` |

| Verification | Result |
|---|---|
| Backend full suite | **886 passed, 7 skipped, 0 failed** |
| Vitest, TypeScript, lint, build | 111 passed (15 files); pass; exit 0 (same 12 pre-existing warning files); pass |
| Browser checks (launcher) | 25/25, 12/12, 6/6, 17/17, 18/18, 16/16 |
| Concurrency | 2 concurrent sales: no lost update, never negative (tests) |
| `backend/shoppulse.db` | SHA-256 `63c44cad…`, 303,104 bytes, modification time unchanged; no schema, model or migration file changed |

## 2026-11-19 – Phase 1 finalisation: invoice review units and fractional quantities

Approved requirements: a missing invoice unit is never defaulted; the user selects a registered unit; confirmation is blocked while a unit is missing or invalid; fractions on the review screen follow the canonical registry. Details: `FRACTIONAL_INVENTORY.md`.

| Area | Files |
|---|---|
| Review screen | `src/pages/InvoiceScanner.tsx`: registry unit select, missing / unregistered unit warning (needs review), `unit-block` banner, unit-aware fraction block and quantity step, payload without the `'pcs'` default |
| Helpers | `src/utils/invoiceReliability.ts` (`unitProblem`, `unitProblemText`, `unitBlockNotice`, `quantityProblem`, `fractionalUnitList`, `fractionalQuantityNotice`, all taking the registry index); `src/utils/unitRegistry.ts` (`maxFractionDigits`) |
| Tests | new `src/tests/invoiceUnitsFraction.test.ts` (14); `src/tests/invoiceReliability.test.ts` (P0 tests updated) |
| Browser checks | new `scripts/e2e/invoice_units_fraction_check.cjs` (36 checks, in the launcher); `fractional_quantity_block_check` (2.5 box), `invoice_metadata_check` (2.5 kg confirmed); token set by `addInitScript` in every check (401 race on `GET /units`) |

| Verification | Result |
|---|---|
| Backend full suite | **886 passed, 7 skipped, 0 failed** (no backend code changed in the finalisation) |
| Vitest | **124 passed (16 files)** |
| TypeScript, lint, build | pass; exit 0 (warnings only in the pre-existing files, none in changed files); pass |
| Browser checks (launcher) | mobile 25/25, metadata 14/14, direct upload 6/6, promotions 17/17, fractional block 18/18, unit registry 16/16, invoice units and fractions 36/36 |
| `backend/shoppulse.db` | SHA-256 `63c44cad…`, 303,104 bytes, modification time unchanged; no migration |

## 2026-11-19 – Voice-to-Bill: spoken prices and units through cart and sale (uncommitted)

Details: `VOICE_TO_BILL.md`.

| Area | Files |
|---|---|
| Backend | `services/voice_parser.py`, `services/inventory_matcher.py`, `schemas/voice.py` (additive `price_source`, `spoken_quantity`, ambiguous `spoken_price` / `options`); new `tests/test_voice_pricing.py` |
| Frontend | `src/utils/cartPricing.ts`, `src/utils/voiceBill.ts` (new), `src/components/VoiceBillModal.tsx`, `src/pages/Sales.tsx`, `src/utils/multilingualVoiceParser.ts`, `src/types/sale.ts`, `src/api/voice.ts`; new `src/tests/voicePricing.test.ts`; 3 voice tests use a kg-stocked rice |
| Browser | new `scripts/e2e/harness/sales.{html,tsx}`, `scripts/e2e/voice_bill_price_check.cjs` (in the launcher) |
