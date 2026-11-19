# Proposal: money columns `Float` → `Numeric(14,3)` — NOT EXECUTED

**Status: proposal only. No migration was written into `alembic/versions`, no table was altered, no data was converted.**
Quantities are deliberately **out of scope** (see `FRACTIONAL_QUANTITY_PROPOSAL.md`).

## 1. Why, and what already works without it

- **Already done in the application, no schema change:** printed values keep up to 3 decimals in extraction, review, the confirm request, the API response, the purchase record, prints and the Excel export. Calculated amounts are rounded half-up to 3 decimals instead of to paise.
- **What `Float` still cannot guarantee:** exact decimal arithmetic. A double stores 62.988 as 62.98799999999999… and prints it back as 62.988, so reading and writing is lossless for up to about 15 significant digits. Sums and products are binary, though (0.1 + 0.2 = 0.30000000000000004). Today the application rounds every stored total in `Decimal` before writing, which keeps stored values clean, but SQL aggregates (`SUM(sales.total_amount)` in dashboards and insights) still add doubles.
- **What `Numeric(14,3)` adds:** exact storage and exact SQL arithmetic, up to ₹99,999,999,999.999.

## 2. Current state (inspected read-only)

| Table.column | Type today | Nullable | Notes |
|---|---|---|---|
| `products.selling_price` | Float | NO | |
| `products.purchase_price` | Float | yes (default 0.0) | NULL = cost unknown (free-line products) |
| `products.mrp` | Float | yes | |
| `purchases.total_amount` | Float | NO (default 0.0) | |
| `purchase_items.purchase_price` | Float | NO | printed rate; 0.00 for printed free lines |
| `purchase_items.line_amount` | Float | yes | printed line amount |
| `purchase_items.mrp` | Float | yes | |
| `sales.total_amount` | Float | NO (default 0.0) | |
| `sale_items.unit_price` | Float | NO | |
| quantities: `products.current_stock`, `products.reorder_level`, `purchase_items.quantity`, `sale_items.quantity` | Integer | – | **not changed by this proposal** |

How the schema is created today:
- `main.init_db_schema()` runs `Base.metadata.create_all` and then adds missing columns with `ALTER TABLE … ADD COLUMN` (its `INCREMENTAL_COLUMNS` list).
- Alembic revisions exist (`0bdf0ba4cc18`, `1a2b3c4d5e6f`, `2b3c4d5e6f70`), but the local database has no `alembic_version` table and `alembic.ini` holds a placeholder URL. Deployed databases may never have been stamped.
- Default database: SQLite (`backend/shoppulse.db`, 0 rows locally). PostgreSQL is supported through `DATABASE_URL` (`postgresql` dialect imports in the models).

## 3. Everything that depends on these columns

**Backend services**
- `services/invoice.py`:
  - writes: `products.purchase_price / selling_price / mrp`, `purchase_items.*`, `purchases.total_amount`;
  - arithmetic in `Decimal`;
  - duplicate-line merge;
  - confirm response.
- `services/purchase.py` (manual purchases):
  - `quantity * purchase_price` in float;
  - writes `purchases.total_amount`.
- `services/sale.py`:
  - `quantity * unit_price` in float;
  - writes `sales.total_amount` and `sale_items.unit_price`.
- `services/dashboard.py`:
  - `SUM(sales.total_amount)` with `COALESCE(…, 0.0)`;
  - returns product prices.
- `services/insights.py`:
  - `SUM(sales.total_amount)`;
  - `SUM(sale_items.quantity * sale_items.unit_price)`;
  - price fields in responses.
- `services/notification.py`: `SUM(sales.total_amount)` (daily summary).
- `services/search.py`: `purchase.total_amount or 0.0`, `sale.total_amount or 0.0`.
- `services/product.py`, `services/product_lookup.py`, `services/inventory_matcher.py`:
  - read and write prices;
  - `inventory_matcher` rounds sale prices to 2 decimals (`round(…, 2)`).
- `services/mrp_lookup.py`, `services/openmrp_client.py`: MRP values.

**Schemas (Pydantic, `float`)**
- `schemas/product.py`
- `schemas/purchase.py`
- `schemas/sale.py`
- `schemas/invoice.py`
- `schemas/search.py`
- `schemas/insights.py`
- `schemas/voice.py`

With `Numeric(14,3)` the ORM returns `Decimal`. Pydantic `float` fields accept `Decimal`, and JSON keeps the same numbers, so **the API wire format is unchanged**.

**API responses**
- products
- purchases (list, detail)
- sales
- dashboard
- insights
- search
- notifications (amounts in message text)
- invoices (extract and confirm)

**Exports and reports**
- `/invoices/{id}/excel` audit workbook: values are written as `float` from `Decimal`, format `#,##0.00#`.
- Frontend prints and records:
  - `PrintDocuments` (purchase and sale prints);
  - `PurchaseRecordModal`;
  - receipt generator (`receiptGenerator.ts`, 2-decimal sale receipts).
- Analytics blocked-capital estimate (`analyticsService.ts`).

**Frontend:** all values arrive as JSON numbers, so no change is needed. Displays already use `formatPrintedCurrency` for purchases and `formatCurrency` (2 decimals) for sales.

## 4. Proposed migration (to be written only after approval)

**Step 1 – application code, deployable before the migration (backward compatible)**
1. In `db/models/*.py`, change the listed columns to `Numeric(14, 3, asdecimal=True)`.
2. Arithmetic on these values:
   - `services/purchase.py` and `services/sale.py` compute totals in `Decimal` (half-up, 3 decimals);
   - `insights` / `dashboard` / `notification` / `search` replace `COALESCE(…, 0.0)` with `COALESCE(…, 0)` and convert to `float` (or `Decimal`) at the response;
   - `inventory_matcher` keeps 2-decimal *selling* prices (a display and selling decision, not printed invoice data).
3. Notification message formatting uses the printed-precision formatter.

**Step 2 – one Alembic revision `xxxx_money_numeric_14_3`**
- **PostgreSQL:**
  ```
  ALTER TABLE products ALTER COLUMN selling_price TYPE numeric(14,3) USING round(selling_price::numeric, 3);
  … (same for every column in section 2; NOT NULL / defaults kept)
  ```
- **SQLite** (cannot alter a column type):
  - use `op.batch_alter_table(table, recreate="always")` per table;
  - this creates a new table with NUMERIC columns, copies rows with `ROUND(col, 3)`, drops the old table and renames;
  - indexes and foreign keys are recreated from the model;
  - run with `PRAGMA foreign_keys=OFF` during the copy, then `PRAGMA foreign_key_check`.
- **Startup path:** `init_db_schema()` must not fight the migration, because `create_all` never alters existing tables. Add a startup check that logs (never alters) when a money column is still `REAL`/`FLOAT` after the code is deployed.
- **Stamping:** databases created by `create_all` must first be stamped to `2b3c4d5e6f70` (`alembic stamp`), after verifying that the columns of the earlier revisions exist.

## 5. Existing-record conversion

| Value today | After `ROUND(x, 3)` | Effect |
|---|---|---|
| 62.988 (stored 62.98799999999999…) | 62.988 | none visible |
| 13.280000000000001 | 13.280 | binary noise removed |
| 22.0 | 22.000 | none |
| a value with more than 3 decimals (not produced by the app; possible from manual API use) | rounded half-up to 3 decimals | **changes the value**: rows are listed before converting (query below) |
| NULL | NULL | unchanged (`products.purchase_price` NULL = unknown cost stays NULL) |

Pre-migration audit query, run and reviewed before converting:
```sql
SELECT 'products' t, id, selling_price v FROM products WHERE abs(selling_price*1000 - round(selling_price*1000)) > 1e-6
UNION ALL … (one SELECT per column)
```
No rows are deleted or added, and no quantities are touched.

## 6. Backup

1. Stop the backend (no writes during the copy).
2. Back up:
   - SQLite: copy `shoppulse.db` (plus any `-wal` / `-shm` files) to `shoppulse.db.pre-numeric-<date>`, and verify the copy with `PRAGMA integrity_check`;
   - PostgreSQL: `pg_dump -Fc` and a test restore into a scratch database.
3. Record row counts and the column sums (`SUM` of each money column) before the migration, to compare after it.

## 7. Rollback

- **Fast path:** stop the backend and restore the backup file or dump; deploy the previous application build.
- **In place:** `alembic downgrade -1` converts back to `Float` (SQLite: batch recreate; PostgreSQL: `TYPE double precision`). This is lossless, because 3-decimal values convert exactly enough to doubles.
- The step-1 application code works with both `Float` and `Numeric`, so a rollback needs no code change.

## 8. Compatibility testing (before approval of execution)

1. Run the full backend `pytest` against both an SQLite and a PostgreSQL database with the new types. The suite currently runs on SQLite only; PostgreSQL needs a test container.
2. Migration rehearsal on a copy of each real database:
   - row counts equal;
   - every column sum equal to 0.001;
   - `PRAGMA foreign_key_check` clean;
   - the audit query empty, or its rows reviewed.
3. API contract tests: every endpoint in section 3 returns the same JSON numbers before and after (golden responses).
4. Frontend: vitest, e2e mobile (25 checks), invoice metadata (11) and direct upload (6); purchase print shows ₹62.988; dashboard and insights totals unchanged.
5. Downgrade rehearsal followed by an upgrade again, with the same checks.

## 9. Risks

- SQLite table rebuild on large tables: time and disk need about twice the table size. Mitigated by doing it offline with a backup.
- Hidden float assumptions (`== 0.0`, `json.dumps` of `Decimal` outside Pydantic) could surface as `TypeError`. Mitigated by the full suite on both databases and the golden-response tests.
- Unstamped databases: running `alembic upgrade` without stamping would try to recreate tables. Mitigated by the explicit stamp procedure in section 4.
- Precision of `Numeric(14,3)`: the maximum is ₹99,999,999,999.999 per value, which is sufficient for a shop.

**Approval needed:**
- (a) the step-1 application code;
- (b) writing the revision;
- (c) executing it on each environment after the rehearsal.
