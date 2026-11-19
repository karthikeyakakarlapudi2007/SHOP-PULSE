# Phase 4 – Database migration proposal (NOT EXECUTED)

Status: **proposal only [R].**
- No migration file written; no table altered; no data converted; `alembic stamp` not run.
- `backend/shoppulse.db` was only read, in read-only mode.

This proposal supersedes `docs/ocr-reliability/MIGRATION_PROPOSAL_NUMERIC_14_3.md`. That document's §1 claimed exact SQLite storage and exact SQL sums, which is **wrong** [C, probed]; the claim holds only on PostgreSQL.

## 1. Is a migration needed?

| Database | Fractional quantities | Exact money |
|---|---|---|
| SQLite (default) | **Not for storage** [C]: INTEGER columns already store 2.5 (as REAL) and SQLAlchemy reads 2.5. The limit is app-level | Not achievable in storage (REAL); achieved in the app by `Decimal` quantisation on write and read |
| PostgreSQL (supported through `DATABASE_URL`) | **Yes** [A]: `integer` rejects 2.5 | **Yes** [A]: `numeric` is exact |

**[R]** One reviewed Alembic revision that declares the target types and adds the new nullable columns. It's needed for PostgreSQL and for an honest schema. Workstreams 2 and 4 don't depend on it on SQLite.

## 2. Representation options [C: SQLite 3.53.1, SQLAlchemy 2.1.9]

| Option | Exact storage | Exact SQL SUM | Comparisons | Impact | Verdict |
|---|---|---|---|---|---|
| SQLAlchemy `Numeric(p,3)` | SQLite: no (REAL); PostgreSQL: yes | SQLite raw: no (0.1+0.2 = 0.30000000000000004); read through SQLAlchemy: `Decimal('0.300')` | correct | small | **Recommended [D-7]** |
| Decimal as TEXT | yes | no: `SUM` casts to REAL | **wrong** (text comparison) unless cast everywhere | large | rejected |
| Integer minor units (×1000) | yes | yes (100+200 = 300) | correct | very large; every read and write ×/÷1000; high error risk | not now; reconsider only if exact raw-SQL totals on SQLite become mandatory |

## 3. Columns
- **Existing columns change type:**

  | Column | Today | Proposed |
  |---|---|---|
  | products.current_stock, products.reorder_level | Integer | Numeric(12,3) |
  | purchase_items.quantity, sale_items.quantity | Integer | Numeric(12,3) |
  | products.selling_price, purchase_price (NULL = unknown cost), mrp | Float | Numeric(14,3) |
  | purchases.total_amount, sales.total_amount | Float | Numeric(14,3) |
  | purchase_items.purchase_price, line_amount, mrp; sale_items.unit_price | Float | Numeric(14,3) |

  Nullability and defaults stay as they are.
- **New columns (all nullable), from `DESIGN.md` §4:**

  | Table | Essential | Optional |
  |---|---|---|
  | purchase_items | printed_quantity, purchase_unit, inventory_unit, conversion_factor, paid_quantity, free_quantity | discount_amount, taxable_amount, gst_rate, cgst_amount, sgst_amount, igst_amount, quantity_text [D-5] |
  | sale_items | unit, line_total | entered_quantity, entered_unit |
  | purchases | – | printed_total, total_reconciliation_status, tax_total, discount_total |
  | new table (only if D-4 approved) | `product_unit_conversions` (product_id, from_unit, to_unit, factor, confirmed_by, created_at) | – |

## 4. Existing and historical records
- **Integer quantities:** 5 becomes 5.000, exactly.
- **Money:** `ROUND(x, 3)`. The audit query runs first and its rows are reviewed:

  ```sql
  SELECT 'products.selling_price' c, id, selling_price v FROM products
   WHERE abs(selling_price*1000 - round(selling_price*1000)) > 1e-6
  UNION ALL … -- one SELECT per money column
  ```

- **Historical totals are not recomputed.** Float noise becomes 3 dp (0.30000000000000004 → 0.300).
- **New columns stay NULL for old rows.** Optional backfill for inventory_unit is the product's current unit, marked as a backfill [R]. Unknown cost stays NULL.
- No rows added or deleted.
- **Local database:** contains only test rows (`BASELINE_AUDIT.md` §9). Cleanup is a separate decision [D-10]. The rehearsal should use a fixture database, not that file.

## 5. Procedure (after approval)
1. **Deploy workstreams 4 and 2 first;** they work on both the old and new column types.
2. **Back up:**
   - stop the backend;
   - SQLite: copy the file plus `-wal` / `-shm`, then `PRAGMA integrity_check` on the copy;
   - PostgreSQL: `pg_dump -Fc` and a test restore;
   - record row counts and per-column `SUM`s.
3. **Stamp:** databases built by `init_db_schema()` have no `alembic_version`. Stamp them to `2b3c4d5e6f70` after checking that the earlier revisions' columns exist. (Not done in Phase 0.)
4. **Revision:**
   - SQLite: `batch_alter_table(recreate="always")` per table, copying `ROUND(col,3)`, with `PRAGMA foreign_keys=OFF` during the copy and `foreign_key_check` after;
   - PostgreSQL: `ALTER COLUMN … TYPE numeric(p,3) USING round(col::numeric,3)`, then `ADD COLUMN` for the new nullable columns.
5. **`main.init_db_schema()`:** add the new columns to `INCREMENTAL_COLUMNS` so fresh databases match. A start-up check **logs** (never alters) columns still typed INTEGER/REAL.
6. **Verify:**
   - counts equal;
   - per-column sums equal to 0.001;
   - foreign keys clean;
   - audit rows reviewed.

## 6. Rollback
- **Fast:** restore the backup and redeploy the previous build.
- **In place:** `alembic downgrade -1`.
  - Money goes back to Float (lossless for 3-dp values).
  - Quantities go back to Integer, which is **lossy**, so the downgrade **refuses** while any fractional quantity exists and lists those rows.
  - New columns are dropped; this loses only data recorded after the upgrade, which the backup still contains.
- The workstream 2 and 4 code runs on both schemas, so no code rollback is needed for the schema rollback.

## 7. Migration tests
1. Upgrade, downgrade and upgrade again on a fixture database (integers, 3-dp money, NULL costs, promo lines, fractional stock).
2. Rehearsal on a copy of each real database: counts, sums, foreign keys, audit query.
3. The full backend suite on SQLite and on PostgreSQL. **[U]** The PostgreSQL run needs a test container that isn't in the repository today.
4. API contract golden responses compared before and after.
5. Vitest and all browser checks, including the new fractional checks at phone width.
