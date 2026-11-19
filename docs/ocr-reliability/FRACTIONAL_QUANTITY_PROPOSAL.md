# Investigation and proposal: fractional inventory quantities (2.5 kg, 0.75 L)

**Status: P0 implemented (approved). P1 and P2 are not implemented.** Whole-number stock behaviour is unchanged.
This is separate from the money-precision migration (`MIGRATION_PROPOSAL_NUMERIC_14_3.md`), which must not change
quantities and remains unapproved.

## 0. P0 as implemented

- **Review screen:** a selected line whose quantity, paid units or free units is not a whole number blocks
  confirmation. A banner explains that fractional stock quantities are not currently supported and that nothing has
  been added to stock. The banner has no button that bypasses it.
- **Correcting the line:**
  - the extracted reading stays in the field and is shown as "Read as 2.5 kg", so it can be corrected (for example
    as 5 × 500 g packs) or the line can be deselected;
  - the banner clears once no selected line is fractional.
- **Confirm payload:** sends the quantity unchanged (the `Math.max(1, Math.round(...))` rounding was removed).
- **Backend (`InvoiceConfirmItem`):** rejects a fractional `quantity`, `paid_quantity` or `free_quantity` with a
  clear 422 message.
  - The check runs during request validation, before any write, so **no stock, product or purchase is recorded for
    the invoice**.
- **Tests:**
  - `test_phase3a_confirm_precision_promotions.py` (`test_p0_*`);
  - `src/tests/invoiceReliability.test.ts` (P0 block);
  - `scripts/e2e/fractional_quantity_block_check.cjs` (desktop and Pixel 7, 18 checks).

## 1. Current behaviour (verified by running it)

| Path | Quantity type | 2.5 / 0.5 today |
|---|---|---|
| DB `products.current_stock`, `products.reorder_level` | Integer | cannot hold 2.5 |
| DB `purchase_items.quantity`, `sale_items.quantity` | Integer | cannot hold 2.5 |
| `POST /sales` (`SaleItemCreate.quantity: int`) | int | **rejected** (422 `int_from_float`) |
| `POST /purchases` (`PurchaseItemCreate.quantity: int`) | int | **rejected** (422) |
| `POST /invoices/confirm` (`whole_units` validator) | whole float | **rejected** (422 "quantity must be a whole number of stock units") |
| Invoice extraction (OCR) | Decimal, 3 decimals | 2.5 kg extracted correctly (e.g. TC15 "2.5 kg", "0.75 kg") |
| Voice-to-Bill parser (`voice_parser.py`) | `int \| float` | "0.5 kg sugar" → 0.5, then the sale is rejected by `/sales` |
| Weighing scale (`scaleService.ts`) | number, 3 decimals | net weight 0.750, then the sale is rejected by `/sales` |
| **Invoice review → confirm (frontend)** | before P0: `Math.max(1, Math.round(quantity))` | before P0: **2.5 silently posted as 3; 0.4 as 1**. After P0: blocked with an explanation |

**Pre-existing silent change, the most important finding:** `src/pages/InvoiceScanner.tsx` builds the confirm payload with `quantity: Math.max(1, Math.round(Number(i.quantity)))`.
- The backend would reject 2.5 with a clear message, but the frontend rounds first, so the user is never told.
- This predates Phase 3A.
- Fixed by P0 (section 0): confirmation is blocked with an explanation instead of rounding.

## 2. Options

**P0 – Stop the silent rounding — IMPLEMENTED (section 0)**
- Frontend:
  - if a selected line's quantity is not a whole number, show the message above and do not post;
  - the quantity input keeps `step="1"`.
- No schema change and no change to stock arithmetic.
- **Risk:** users with loose-weight lines must edit them (e.g. enter 3 bags instead of 2.5 kg) before confirming. This is the existing rule, made visible.

**P1 – Whole-unit stock with unit conversion (no fractional stock)**
- Products sold loose are stocked in their smallest unit (grams, ml), so 2.5 kg becomes 2500 g, an integer.
- Needs a per-product base unit and a conversion at extraction, voice and scale time.
- **Risk:**
  - every existing product with unit "kg" would need its stock re-expressed, which is a data migration;
  - prices per kg would become prices per g, so display conversions are needed everywhere;
  - a high risk of ×1000 errors.
- **Not recommended.**

**P2 – Fractional stock (`Numeric(12,3)` quantities) for products whose unit is a measure**
- Schema: `products.current_stock`, `products.reorder_level`, `purchase_items.quantity` and `sale_items.quantity` become `Numeric(12,3)`. Existing integers convert exactly (5 → 5.000).
- Rule: a fractional quantity is accepted only when the product's unit is a measure unit (kg, g, L, ml, m). Count units (pcs, pkt, bag, box) stay whole, enforced by validation, never by rounding.
- Code that must change:

  | Area | Change |
  |---|---|
  | Schemas | `quantity: int` → `Decimal`/`float` with a per-unit validator in `schemas/sale.py`, `schemas/purchase.py`, `schemas/invoice.py` (`whole_units` → unit-aware), `schemas/product.py` (`current_stock: int`), `schemas/search.py`, `schemas/voice.py`, `schemas/insights.py` |
  | Services | `services/sale.py` (stock check `current_stock < quantity`, decrement), `services/purchase.py` (increment), `services/invoice.py` (`qty = int(item.quantity)` at confirm), `services/inventory_matcher.py` (`int(current_stock)`), `services/insights.py` / `services/notification.py` (`int(p.current_stock)`), dashboard `SUM(sale_items.quantity)` |
  | Low-stock and reorder logic | `current_stock <= reorder_level` works for decimals; reorder levels per unit |
  | Frontend | quantity inputs `step="1"` → `step="0.001"` for measure units only; stock display "2.5 kg"; sale cart and receipts; analytics `prod.stock * cost`; inventory filters |
  | Exports and prints | quantity columns show up to 3 decimals for measure units |

- Migration, backup, rollback: same procedure as the money proposal (batch table rebuild on SQLite, `ALTER … TYPE numeric(12,3)` on PostgreSQL). It can be combined with the money migration in one maintenance window but must be a **separate revision**, so each can be rolled back on its own. Downgrade to Integer is lossy for fractional stock, so the downgrade must refuse while any fractional value exists.
- **Risks:**
  - unit mistakes: 2.5 entered for a "pcs" product. Mitigated by the unit-aware validator;
  - floating comparisons in stock checks. Mitigated by using Decimal;
  - reports summing mixed units (kg + pcs) as "units". Totals must be grouped by unit;
  - voice and scale sales start succeeding where they now fail, which needs end-to-end retesting of Voice-to-Bill.

## 3. Recommendation

1. **P0** is implemented.
2. Decide between **P2** (fractional stock for measure units) and keeping whole units.
   - If P2, implement it after the money migration, as its own reviewed change with its own tests: unit-aware validation; sale, purchase and invoice stock movements in kg; Voice-to-Bill 0.5 kg; scale sale 0.750 kg; reports grouped by unit.
3. Keep the money migration free of quantity changes, as you required.
