# Phase 4 – Requirements

Status: **draft for approval.** Markers: see `BASELINE_AUDIT.md`. Every requirement has an acceptance test (AT) run in the validation phase (§5). Requirements that depend on an open decision cite it as [D-n] (§6).

## 1. Quantities

| ID | Requirement | AT |
|---|---|---|
| FQ-1 | Products in a **measure** unit (mass, volume [D-1]) hold fractional stock up to 3 decimals (2.5 kg, 0.75 L, 0.125 kg). | AT-FQ-1 |
| FQ-2 | **Count and package** units (pcs, dozen, packet, box, bottle, bag, …) stay whole. A fraction is rejected with a clear message, **never rounded**. | AT-FQ-2 |
| FQ-3 | Sales, manual purchases and invoice confirmation apply fractional quantities exactly for measure units (2.5 − 0.5 = 2.0 kg). | AT-FQ-3 |
| FQ-4 | Voice-to-Bill "half kg" / "0.5 kg" completes a sale end to end. | AT-FQ-4 (browser) |
| FQ-5 | Invoice review: the P0 block stays for count units; measure-unit fractions are accepted. | AT-FQ-5 (browser, desktop and phone) |
| FQ-6 | Low stock, out of stock, reorder suggestions, notifications and insights work with fractional stock. | AT-FQ-6 |
| FQ-7 | Paid and free quantities stay separate, are persisted [D-6], and may be fractional only for measure units. | AT-FQ-7 |
| FQ-8 | Quantities display up to 3 decimals without trailing zeros, with their unit (2.5 kg, 12 pcs). | AT-FQ-8 |
| FQ-9 | **Concurrent sales or purchases never lose a stock change** (today's probe: 2 sales, stock off by 1). | AT-FQ-9 (concurrency test) |

## 2. Units

| ID | Requirement | AT |
|---|---|---|
| FU-1 | One canonical unit registry serves OCR, voice, products, purchases, sales and reports. The four existing vocabularies map onto it; no fifth list is added. | AT-FU-1 |
| FU-2 | Conversions only within a family: kg↔g (×1000), L↔ml (×1000), dozen↔pcs (×12). | AT-FU-2 |
| FU-3 | Packets, boxes, bottles, bags, … never convert to weight, volume or pieces automatically. Only a user-confirmed **product-specific** conversion may do so [D-4]. | AT-FU-3 |
| FU-4 | Stock is kept in the product's inventory unit. Compatible input is converted (500 g into a kg product → +0.5). Incompatible input is rejected or sent to review, never added as a plain number. | AT-FU-4 |
| FU-5 | The printed or entered unit and the conversion factor are kept on the purchase line for audit. | AT-FU-5 |

## 3. Money

| ID | Requirement | AT |
|---|---|---|
| FM-1 | Backend money arithmetic uses `Decimal` with explicit half-up rounding; no float sums (fixes the probed `0.30000000000000004`). | AT-FM-1 |
| FM-2 | Purchase values keep printed precision up to 3 decimals (existing Phase 3A rule). | AT-FM-2 (existing tests) |
| FM-3 | Sale line = round(qty × unit price, 2) half-up; bill = Σ lines [D-2]. Example: 0.750 kg × ₹44.50 = ₹33.38. | AT-FM-3 |
| FM-4 | Prices are per inventory unit. A conversion changes the **quantity, never the rate** (avoids rounding errors in per-gram rates). | AT-FM-4 |
| FM-5 | Dashboard, insights, notifications, reports and receipts show the stored values to the paisa (no raw floats, e.g. the WhatsApp receipt). | AT-FM-5 |
| FM-6 | Valuation and profit use exact qty × cost; rounding happens only for display. | AT-FM-6 |
| FM-7 | API JSON keeps numbers (no strings); existing clients are unaffected. | AT-FM-7 (contract tests) |
| FM-8 | Printed invoice tax and discounts are recorded as printed, never recomputed [D-5]. | AT-FM-8 |

## 4. Non-functional

| ID | Requirement |
|---|---|
| NF-1 | No feature removed or weakened. The full backend, Vitest and browser suites stay green after every workstream. |
| NF-2 | No data loss. Existing records convert exactly; historical totals are not recomputed. |
| NF-3 | The migration is reversible (backup and a guarded downgrade) and rehearsed on a copy first. |
| NF-4 | No new dependency without approval (e.g. `decimal.js`) [D-9]. |
| NF-5 | No private invoice data in code, tests or docs. |
| NF-6 | No horizontal overflow at phone width with 3-dp quantities. |
| NF-7 | Tests and browser checks can never write to the default development database. |

## 5. V-Model traceability

| Left side (definition) | Right side (verification / validation) |
|---|---|
| Requirements (this document) | **Acceptance tests** AT-*: browser checks at desktop and phone width, end-to-end flows |
| System design (`DESIGN.md` §2–§8) | **System and integration tests:** API contract golden responses; concurrency test; migration rehearsal |
| Detailed design (per workstream, `DESIGN.md` §10) | **Integration tests** per workstream (service and database, API) |
| Implementation | **Unit tests** (registry, conversions, validators, money helpers, formatters) |

## 6. Decisions [D]

**D-1 … D-11 were approved on 2026-11-19 (Phase 1).** D-7 still needs the separate migration approval gate. D-10 is limited to a backup: no deletion without separate approval.

| # | Decision | Recommendation |
|---|---|---|
| D-1 | Which units may be fractional | kg, g, L, ml (quintal and tonne only if you sell in them) |
| D-2 | Sale rounding | per line to paise, bill = Σ lines |
| D-3 | Sale price precision | 3 dp per inventory unit (₹44.125/kg allowed; bill in paise) |
| D-4 | Product-specific conversions (1 box = 24 pcs, 1 bag = 25 kg) | in scope as **optional, user-confirmed** per product; never inferred |
| D-5 | Persist printed tax and discounts per purchase line | yes, as optional nullable columns (§ data model in `DATABASE_MIGRATION_PROPOSAL.md`) |
| D-6 | Persist paid/free breakdown | yes (essential) |
| D-7 | Database representation | SQLAlchemy `Numeric` (12,3 quantity; 14,3 money) |
| D-8 | Concurrency fix | atomic conditional SQL updates |
| D-9 | Frontend decimal helper | extend `decimalCalc.ts` (no new dependency) |
| D-10 | Cleanup of the test-only rows in `backend/shoppulse.db` | back up, then delete the file (it is recreated empty on start), per `DESIGN.md` §9 |
| D-11 | Test-database guard (§NF-7) | add it in workstream 9, before any other browser run |
