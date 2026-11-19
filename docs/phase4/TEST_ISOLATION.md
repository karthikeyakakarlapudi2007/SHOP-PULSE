# Phase 4 – Workstream 9a: Test database isolation

Status: implemented, not committed. Requirement NF-7 / decision D-11 (`REQUIREMENTS.md`).

## 1. Why

**Audit findings (`BASELINE_AUDIT.md` §9):**
- browser checks wrote test accounts and records into the development database `backend/shoppulse.db`;
- every backend test run connected to that file, because importing `main` runs `init_db_schema()` on the default engine.

**Root cause [C]:**
- `vite.config.ts` contains `autoBackendPlugin`. When Vite starts and nothing answers on port 8000 within 350 ms, it starts `backend/main.py` itself, without `DATABASE_URL`, so on the default database.
- On 2026-11-18 Vite started before the throwaway test backend was ready. Its own backend took port 8000, and the test backend failed to bind (`address already in use`).
- The browser checks then wrote through Vite's backend.
- **Found during 9a [C]:** **Vitest loads the same `vite.config.ts`, so every `npx vitest run` also started `backend/main.py` on port 8000.**
  - Proven by running Vitest with `DATABASE_URL` pointed at a scratch file: the scratch database was created, and `[Shelfora] … Auto-starting backend` was logged.
  - Without `DATABASE_URL`, that backend opens `backend/shoppulse.db`. Frontend unit-test runs were therefore a second, regular way the development database was opened.

## 2. Requirements (V-Model: left side)

| ID | Requirement | Verified by |
|---|---|---|
| TI-1 | Automated backend tests never open `backend/shoppulse.db`. | unit and integration tests; repeated full runs with a fingerprint check |
| TI-2 | Test mode without an explicit test database, or with the development database, stops before any engine exists (fail closed). | `test_db_safety.py` (unit and subprocess) |
| TI-3 | Browser checks use their own backend, their own database, dedicated ports and a predictable start-up. | launcher run |
| TI-4 | If a test port is already in use, the run stops with a clear error and never talks to an unknown server. | port-guard test |
| TI-5 | Browser checks cannot be run against development servers or without the launcher. | refusal tests |
| TI-6 | The development database is unchanged after any test run, including repeated runs. | launcher self-check; backend fingerprint before and after |
| TI-7 | Normal development (`npm run dev`, backend on 8000, default database) behaves as before. | outside test mode the guard is a no-op; the Vite defaults are unchanged |

## 3. Design

### 3.1 Safety guard: `backend/core/db_safety.py`
- **Test mode** is on when `SHOPPULSE_TEST_MODE` is `1/true/yes`, **or** when `pytest` is imported in the process. The second rule catches a run that bypasses `conftest.py`.
- **In test mode, `db/session.py` calls `guard_database_url()` before creating the engine.** It raises `UnsafeTestDatabaseError` when:
  - `DATABASE_URL` is not set (the app would fall back to the default database);
  - the URL is not SQLite (a server database can't be verified as a throwaway one);
  - the URL can't be parsed;
  - the SQLite file resolves to `backend/shoppulse.db` (relative paths, `..` tricks and `file:` URIs are resolved first), or is any file named `shoppulse.db*`;
  - the SQLite file lies inside `backend/`, next to the development database.
- In-memory SQLite and temporary-directory files are accepted.
- **Outside test mode the guard does nothing.**

### 3.2 Backend tests: `backend/tests/conftest.py`
- **Before any test module imports `main`, it:**
  - creates a temporary directory `shoppulse-pytest-*`;
  - sets `SHOPPULSE_TEST_MODE=1`;
  - sets `DATABASE_URL=sqlite:///<tmp>/test.db`.
- **Inherited values are replaced:** any `DATABASE_URL` from the shell or `.env` is overwritten (environment variables take precedence over `.env` in the settings). `SHOPPULSE_TEST_DATABASE_URL` may name another test database, and the same guard checks it.
- **The engine is asserted:** a session fixture asserts that the application engine points at that database.
- **Reporting and clean-up:** the pytest header prints the test database, and the directory is removed when the run ends.
- **Existing per-file in-memory databases:** test files that create their own in-memory engines and override `get_db` keep working unchanged.

### 3.3 Browser checks: `scripts/e2e/run.cjs` and `scripts/e2e/e2e_env.cjs`

| Item | Value |
|---|---|
| Test backend | `127.0.0.1:8765` (`E2E_BACKEND_PORT`) |
| Test web server (Vite) | `127.0.0.1:5174` (`E2E_WEB_PORT`), `--strictPort` |
| Development ports 8000 / 5173 | always refused |
| Test database | `sqlite:///<tmp>/shoppulse-e2e-*/e2e.db`, new each run |

Launcher sequence:
1. **Port guard:** each test port must refuse connections on 127.0.0.1 and [::1] and be bindable. Otherwise it stops with exit code 2 and says which port and why.
2. **Fingerprint:** SHA-256, size and modification time of `backend/shoppulse.db`, `-wal` and `-shm`.
3. **Test backend:** started with `SHOPPULSE_TEST_MODE=1` and the temporary `DATABASE_URL`. The backend's own guard would refuse anything else.
4. **Test Vite:** started with `SHOPPULSE_TEST_MODE=1`, so **no auto-started backend**. `SHOPPULSE_API_TARGET` points the `/api` proxy at the test backend, and `VITE_API_URL` is empty so the page uses the proxy.
5. **Readiness:** each server must answer and stay alive. If either exits during start-up (e.g. it couldn't bind), the run stops; it never falls back to another server. `/api/v1/health` must answer through the Vite proxy.
6. **Checks:** asset preparation, then each check, with `E2E_LAUNCHED=1`, `API_URL` and `WEB_URL`. A check passes only if it exits 0, prints `N/N checks passed` and prints no `FAIL`.
7. **Teardown:** stops only the two process groups it started, then compares the fingerprint. **Any change to the protected files fails the run.** The temporary directory is removed (kept on failure, or with `E2E_KEEP=1` / `E2E_ARTIFACT_DIR`).

`e2e_env.cjs` is used by every check. It refuses to run (exit 2) unless `E2E_LAUNCHED=1` and both URLs are set, local, and not on a development port.

### 3.4 `vite.config.ts` (development defaults unchanged)
- **`SHOPPULSE_API_TARGET`:** the proxy target; default `http://127.0.0.1:8000`.
- **`SHOPPULSE_TEST_MODE=1`, or a Vitest run (`VITEST` set):** the backend auto-start plugin is not loaded.
- **Regression test:** `src/tests/testIsolation.test.ts` asserts that the plugin is absent under Vitest and that the proxy keeps its development default.

## 4. How to run tests safely

```bash
# Backend (any directory layout; conftest isolates the database automatically)
cd backend && .venv/bin/python -m pytest -q

# Browser checks (all, or by name)
node scripts/e2e/run.cjs
node scripts/e2e/run.cjs fractional_quantity_block_check review_promotions_precision_check

# Other ports, keeping screenshots
E2E_BACKEND_PORT=8865 E2E_WEB_PORT=5274 E2E_ARTIFACT_DIR=/tmp/e2e-shots node scripts/e2e/run.cjs
```

Running a check directly (`node scripts/e2e/<check>.cjs`) is refused by design.

## 5. Verification results (executed 2026-11-19)

| Level | Test | Result |
|---|---|---|
| Unit | `test_db_safety.py`: URL selection, refusals, test-mode detection | 20 passed |
| Integration | subprocess `import main`: test mode without `DATABASE_URL` → refused; with the dev database → refused; with a temporary database → schema created there | pass; protected file unchanged |
| Integration | `pytest --noconftest` bypass (no `DATABASE_URL`, or the dev database) | refused at collection |
| Integration | Vite in test mode with nothing on port 8000 | no backend auto-started |
| Integration | Vitest with `DATABASE_URL` set to a scratch file, before and after the fix | before: a backend started (scratch database created); after: none started, no scratch database, nothing on port 8000 |
| Unit (frontend) | `src/tests/testIsolation.test.ts` | 2 passed; Vitest total 104 passed (14 files) |
| System | full backend suite, twice | 687 passed, 7 skipped, 0 failed (both runs) |
| System | all browser checks through the launcher | 25/25, 12/12, 6/6, 17/17, 18/18 |
| Acceptance | protected-file fingerprint before and after every run | unchanged |
| Acceptance | port 8765 or 5174 occupied; dev port requested; direct check run | stopped with exit 2 and a clear message, no request sent |

Full details: `IMPLEMENTATION_LOG.md`.

## 6. Limitations
- **Only enforced in tests:** the guard protects test runs (pytest, or `SHOPPULSE_TEST_MODE`). A developer who starts the backend manually without a `DATABASE_URL`, outside test mode, still uses `backend/shoppulse.db`; that is the intended development behaviour.
- **Server databases are refused:** PostgreSQL and other server databases are always refused in test mode. Running the suite on PostgreSQL (planned for workstream 5) will need an explicit, verifiable test-database rule then.
- **Port race window:** there's a short gap between the port check and the server binding. If another process binds in that gap, the launcher's server fails to start, and the launcher stops instead of using the other server.
- **Shared development database:** if a developer's own backend is running and writing to `shoppulse.db` during a browser run, the launcher's fingerprint check reports a change. That is a correct report, but the cause isn't the test run.
- **Side files:**
  - `backend/shoppulse.db-wal` (0 bytes) and `-shm` were created on 2026-11-19 06:49 by the read-only Phase 0 audit queries. SQLite creates them for WAL databases even on read-only connections.
  - They were **removed during 9a** by a Vitest run made before the Vitest fix. That run's auto-started backend opened the database, and SQLite deletes the side files when the last connection closes.
  - `shoppulse.db` itself has kept the same SHA-256 (`63c44cad…639d`), size (303,104 bytes) and modification time (2026-11-18 18:05:22) throughout. No data changed.
- **Development is unchanged:** `npm run dev` still auto-starts a backend on the default database. This was left as is because it's development behaviour, not test behaviour.
