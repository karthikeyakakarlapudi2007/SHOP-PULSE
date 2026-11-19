# Phase 4 – Fractional inventory and atomic stock updates (Phase 1 finalised)

No schema change, migration or data rewrite. On SQLite the existing INTEGER stock and quantity columns already store
2.5 exactly (verified in the Phase 0 audit), so the SQLAlchemy column types are unchanged.

## Behaviour

**Quantity rules (unit registry, workstream 1):**

| Units | Quantities |
|---|---|
| kg, g, L, ml | up to 3 decimals (2.5 kg, 750 ml, 0.125 kg) |
| pcs, nos, dozen, packet, box, bottle, other packages, quintal, tonne | whole numbers; a fraction is refused, never rounded |

**Products (`POST /products`, `PUT /products/{id}`):**
- a given unit must be registered; unknown text is refused (400);
- stock and reorder level must suit the unit;
- a unit change must suit the existing stock;
- existing products with an unregistered free-text unit still load and keep working, with whole numbers only and no conversion.

**Sales and purchases:**
- `quantity` may be fractional for measure units;
- **new optional `unit`** on sale and purchase lines: a compatible unit is converted into the product's stock unit (250 g into a kg product → +0.25 kg; 750 g sold → −0.75 kg). An incompatible unit (L for a kg product), a package unit without a product-specific conversion, or an unknown unit is refused (400) and nothing changes;
- prices are per stock unit; a conversion changes the quantity, never the rate.

**Invoice confirmation:**
- every line needs a registered unit. A **missing or unknown unit is refused for review** (400, with a message naming the line); it is never assumed to be pcs;
- fractions are accepted for measure units. A fraction in a whole-number unit is still refused (422, the existing P0 message);
- a compatible line unit is converted into the matched product's unit; an incompatible one is refused;
- same-named lines with different units are not merged;
- purchase lines are recorded as printed (quantity and rate in the line's unit).

**Invoice extraction:** a line with no unit, or an unregistered one, is flagged `needs_review` with a reason. Fractional quantities are kept (2.5 kg).

**Invoice review screen (`InvoiceScanner.tsx`, finalisation):**
- **Missing unit:** the line stays empty (no `'pcs'` or `'unit'` default, no unit guessed from the product name). It is marked "Needs review: Unit missing: select the unit printed on the invoice", and its unit select is highlighted as invalid.
- **Unregistered unit** (e.g. `unit`): kept visible as "unit (not registered)" and flagged the same way.
- **Unit selection:** a select lists the registered units from `GET /api/v1/units` (via `useUnitRegistry`, 27 units). Selecting a unit changes only the unit; the extracted quantity, rate and amount are kept. Valid printed units (`kg`, `KGS`, `PKT`, …) are kept as printed and shown as their canonical unit.
- **Confirmation blocked** while a selected line has a missing or unregistered unit: banner `unit-block` names each line. No request is sent and nothing is added to stock. The banner clears as soon as the units are valid. If the registry is still loading or could not be loaded, confirmation is blocked with that explanation; units are never assumed.
- **Fractions follow the registry:** kg, g, L and ml accept up to 3 decimals. The quantity field steps by 0.001 and can be edited (2.5 → 2.75 kg). pcs, dozen, packages, quintal and tonne stay whole: they step by 1, are marked "Whole units only" and block confirmation (banner `fractional-quantity-block`) until corrected. Nothing is rounded.
- **Payload:** `quantity: Number(i.quantity)` and the line's unit as printed or selected. No `Math.round`, `parseInt` or truncation, and no `|| 'pcs'`.
- **No frontend unit list:** every unit, fraction rule and decimal limit comes from the registry index (`createUnitIndex`, now also exposing `maxFractionDigits`). The helpers (`unitProblem`, `unitBlockNotice`, `quantityProblem`, `fractionalQuantityNotice`) take the index as a parameter.
- A manual "Add Item" line starts as `pcs`, shown in the select and changeable; this is a visible choice, not a default for an extracted line.

**Paid + free:** unchanged. Inventory receives paid + free, and only paid units are charged. This now also works with fractions, e.g. 5 + 0.5 kg → stock 5.5 kg, charged 5 kg.

**Integer truncation removed:**
- invoice confirmation `int(quantity)`;
- voice candidate stock;
- insights quantity sold, stock and reorder level;
- notification stock and reorder level;
- dashboard quantities sold.

Counts, IDs and confidence values are unchanged. Quantities print as `5` or `2.5`, and whole values stay integers in JSON.

**Registry additions:** common retail package units bar, sachet, roll, strip, tray and tube, each its own whole-number package family. They were needed so product units used in practice (e.g. `bar`) are not refused.

## Atomic stock updates (`backend/services/stock.py`)

- **Sale:** `UPDATE products SET current_stock = ROUND(current_stock - :q, 3) WHERE id = :id AND current_stock >= :q`. Zero rows affected means insufficient stock, and the whole sale rolls back.
- **Purchase or invoice:** `UPDATE ... SET current_stock = ROUND(COALESCE(current_stock, 0) + :q, 3)`.
- Both run inside the request's transaction (rollback unchanged). The friendly pre-check message is kept, but the conditional update decides.
- `ROUND(…, 3)` keeps fractional stock free of float noise.

## Tests (executed; finalisation figures in the last section)

| Suite | Result |
|---|---|
| New `test_fractional_inventory.py` | **31 passed** |
| Full backend | **886 passed, 7 skipped, 0 failed** (previously 850) |
| Vitest, TypeScript, lint, build | 111 passed (15 files); pass; exit 0 (same 12 pre-existing warning files); pass |
| Browser checks (isolated launcher) | 25/25, 12/12, 6/6, 17/17, 18/18, 16/16 |

The new tests cover:
- 2.5 kg and 750 ml stock; a 0.5 kg sale; a 250 g purchase;
- whole-number rules for pcs and packages; invalid conversions; unknown units; missing invoice units;
- insufficient stock (including the same product twice in one sale);
- **concurrent sales**: 10 kg − 1.5 − 1.5 → 7 (the Phase 0 probe lost one update); 1 kg vs two 0.75 kg sales → one refused, stock 0.25, never negative;
- purchase and sale rollback; invoice conversion; fractional paid + free;
- voice "half kg" → sale; OCR fractions and missing-unit review; report quantities.

**Existing tests updated to the approved rules** (no test deleted or weakened):
- confirm items given an explicit `unit` (32 items in 3 files), replacing the removed silent `pcs` default;
- tests for invoices that print no unit column now assert `needs_review` caused **only** by the missing unit;
- the P0 tests now check fractions in whole-number units (refused) and in kg / L / g (accepted);
- the registry alias test includes the 6 new package units;
- the frontend registry fixture was regenerated;
- the e2e fractional check corrects the line to the registered unit `packet` instead of the free text `500g pack`.

**OCR dataset re-run** (fixtures, synthetic, simulated; in-memory DB):
- every extracted value and header is identical to workstream 4, and accuracy totals are unchanged (fully correct 145 / 102 / 243; silent-wrong 0);
- **lines flagged for review: 143 → 343 of 609** (+200), all from the missing-unit rule. 273 test lines come from invoices without a unit column.

## Limitations

- **Invoices without a unit column need a unit selected on every line** before confirmation. This is by design: a missing unit is never assumed.
- **PostgreSQL:** INTEGER columns cannot hold 2.5. Fractional stock on PostgreSQL needs the approved migration (workstream 5); SQLite works now.
- **Products with unregistered legacy units** keep whole-number behaviour until their unit is changed to a registered one.
- **Package conversions** are product-specific and passed per request only. There is no persistent configuration (needs a migration).

## Finalisation (review screen) – verification

**Frontend tests:**
- new `src/tests/invoiceUnitsFraction.test.ts`, 14 tests against the real registry fixture: missing and unregistered units; block and clear; registry unavailable; unit correction keeps the values; 2.5 kg, 750 ml, 0.125 kg and 2.75 KGS accepted; whole-number units; 3-decimal limit; registry-derived messages; source checks (no default unit, no unit list, step per unit);
- `invoiceReliability.test.ts` P0 tests updated to the unit-aware rule.

**Browser checks:**
- new `scripts/e2e/invoice_units_fraction_check.cjs` (desktop and Pixel 7):
  - missing-unit warning; unregistered unit; confirmation blocked with no request and no stock;
  - unit selected with values kept; 2.5 kg and 750 ml; 2.5 → 2.75 kg edit;
  - 2.5 and 2.25 packet refused, then 3;
  - one request with the exact values; stock 2.75 kg, 750 ml, 3 packets, 20 pcs.
- `fractional_quantity_block_check` now uses a whole-number unit (2.5 box), since kg fractions are valid.
- `invoice_metadata_check` confirms the printed 2.5 kg line instead of deselecting it (stock 3 × 2.5 = 7.5 kg; the duplicate adds nothing).
- All checks set the test token with `addInitScript` before page scripts run. This removes a race where a token-less first load's 401 cleared the token; `GET /units` requires auth.

