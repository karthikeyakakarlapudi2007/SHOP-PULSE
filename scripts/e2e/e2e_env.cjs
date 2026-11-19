/**
 * Shared target for the browser checks (Phase 4, workstream 9a).
 *
 * The checks only run against the isolated test servers started by `node scripts/e2e/run.cjs`, which
 * sets E2E_LAUNCHED, API_URL and WEB_URL. Run directly, or pointed at the development ports
 * (backend 8000, Vite 5173), a check stops before sending any request, because it could otherwise
 * write test data through a development backend into backend/shoppulse.db.
 */
const DEV_PORTS = new Set(['8000', '5173']);

function e2eTarget() {
  const fail = (msg) => {
    console.error(`E2E TARGET REFUSED: ${msg}\nRun the browser checks with: node scripts/e2e/run.cjs [check ...]`);
    process.exit(2);
  };
  if (process.env.E2E_LAUNCHED !== '1') fail('not started by the test launcher (E2E_LAUNCHED is not set).');
  const API = process.env.API_URL;
  const WEB = process.env.WEB_URL;
  if (!API || !WEB) fail('API_URL and WEB_URL must both be set.');
  for (const [name, value] of [['API_URL', API], ['WEB_URL', WEB]]) {
    let url;
    try {
      url = new URL(value);
    } catch {
      fail(`${name} is not a valid URL: ${value}`);
    }
    if (DEV_PORTS.has(url.port)) fail(`${name} uses development port ${url.port}.`);
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) fail(`${name} must point at this machine: ${value}`);
  }
  return { API: API.replace(/\/+$/, ''), WEB: WEB.replace(/\/+$/, ''), HARNESS: `${WEB.replace(/\/+$/, '')}/scripts/e2e/harness/index.html` };
}

module.exports = { e2eTarget };
