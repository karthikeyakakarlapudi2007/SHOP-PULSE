/**
 * Browser check (Phase 4, workstream 1): the real add-product form consumes the canonical unit registry.
 * Unit suggestions come from GET /api/v1/units through the Vite proxy; the unit field stays free text
 * (typed and unknown units are submitted unchanged, never replaced); without the registry the form still
 * works. Desktop and Pixel 7.
 *
 * Run through the isolated test launcher (test backend, test database, dedicated ports):
 *   node scripts/e2e/run.cjs unit_registry_check
 */
const { chromium, devices } = require('playwright');
const { API, WEB } = require('./e2e_env.cjs').e2eTarget();
const FORM = `${WEB}/scripts/e2e/harness/product-form.html`;
const results = [];
const check = (n, ok, d = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? ' — ' + d : ''}`); };

(async () => {
  const H = { 'Content-Type': 'application/json' };
  const email = `units-ui-${Date.now()}@example.com`;
  await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) });
  const { access_token: tok } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) }).then((r) => r.json());
  const registry = await fetch(`${API}/units`, { headers: { Authorization: `Bearer ${tok}` } }).then((r) => r.json());
  check('registry endpoint answers with units', Array.isArray(registry.units) && registry.units.length > 0, `${registry.units?.length} units`);
  check('registry endpoint refuses anonymous requests', (await fetch(`${API}/units`)).status === 401);

  const browser = await chromium.launch();
  for (const [label, opts] of [['desktop', { viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 }], ['phone', { ...devices['Pixel 7'] }]]) {
    for (const apiDown of [false, true]) {
      const tag = `${label}${apiDown ? ' (registry unavailable)' : ''}`;
      const context = await browser.newContext(opts);
      // Token present before the first request (an anonymous 401 would clear a token set later)
      await context.addInitScript((t) => localStorage.setItem('shoppulse_token', t), tok);
      const page = await context.newPage();
      if (apiDown) await page.route('**/api/v1/units', (r) => r.fulfill({ status: 503, body: 'down' }));
      await page.goto(FORM);
      const unit = page.locator('input[id$="-unit"]');
      await unit.waitFor();
      if (apiDown) await page.waitForResponse((r) => r.url().includes('/api/v1/units'), { timeout: 15000 }).catch(() => {});
      else await page.waitForSelector('datalist[data-testid="unit-options"] option', { state: 'attached', timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(300);
      const options = await page.locator('datalist[data-testid="unit-options"] option').evaluateAll((els) => els.map((e) => e.value));
      if (apiDown) {
        check(`${tag}: form still renders, no suggestions, default unit kept`, options.length === 0 && (await unit.inputValue()) === 'pkts');
      } else {
        check(`${tag}: suggestions are the registry units`, JSON.stringify(options) === JSON.stringify(registry.units.map((u) => u.label)), `${options.length} options`);
        check(`${tag}: field stays free text, default unit kept`, (await unit.getAttribute('type')) === 'text' && (await unit.inputValue()) === 'pkts');
      }
      // Submit with an unknown unit: it must be submitted exactly as typed, never replaced
      await page.fill('input[id$="-name"]', `E2E Unit ${tag}`);
      await page.fill('input[id$="-sellingPrice"]', '50');
      await page.fill('input[id$="-purchasePrice"]', '40');
      await page.fill('input[id$="-stock"]', '3');
      await unit.fill(apiDown ? 'kg' : 'bundle-xyz');
      await page.click('button[type="submit"]');
      await page.waitForTimeout(500);
      const submitted = await page.evaluate(() => window.__submitted);
      const expected = apiDown ? 'kg' : 'bundle-xyz';
      check(`${tag}: unit submitted exactly as typed ("${expected}")`, submitted.length === 1 && submitted[0].unit === expected, JSON.stringify(submitted.map((p) => p.unit)));
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      check(`${tag}: no horizontal overflow`, overflow <= 1, `${overflow}px`);
      await page.close();
    }
  }
  await browser.close();
  console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
})().catch((e) => { console.error('SCRIPT ERROR', e); process.exit(1); });
