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
