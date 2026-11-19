/**
 * R10 browser check: a photo sent straight to OCR ("Upload PDF or file") gets the same quality
 * warning and retake advice as the camera flow; a clear photo and a PDF get none.
 *
 * Run through the isolated test launcher (test backend, test database, dedicated ports):
 *   node scripts/e2e/run.cjs direct_upload_warning_check
 */
const { chromium } = require('playwright');
const SP = process.argv[2];
const { API, HARNESS } = require('./e2e_env.cjs').e2eTarget();
const results = [];
const check = (n, ok, d = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? ' — ' + d : ''}`); };
(async () => {
  const H = { 'Content-Type': 'application/json' };
  const email = `warn-ui-${Date.now()}@example.com`;
  await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) });
  const { access_token: tok } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) }).then((r) => r.json());
  await fetch(`${API}/shops`, { method: 'POST', headers: { ...H, Authorization: `Bearer ${tok}` }, body: JSON.stringify({ shop_name: 'K', owner_name: 'R', business_type: 'Grocery/Kirana', location: 'B' }) });
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 })).newPage();
  const assessCalls = [];
  page.on('request', (r) => { if (r.url().includes('/document-prep/assess')) assessCalls.push(r.url()); });
  await page.goto(HARNESS);
  await page.evaluate((t) => localStorage.setItem('shoppulse_token', t), tok);
  async function extract(file) {
    await page.goto(HARNESS);
    await page.click('[role=tab]:has-text("Upload PDF or file")');
    await page.setInputFiles('input[type=file]:not([multiple]):not([capture])', file);
    await page.click('button:has-text("Extract Line Items")');
    await page.waitForSelector('text=Extracted Grocery Line Items', { timeout: 120000 });
  }
  const warning = page.locator('[data-testid="direct-photo-warning"]');

  await extract(`${SP}/poor.jpg`);
  check('poor photo: warning shown after direct upload', await warning.isVisible());
  check('poor photo: retake advised', (await page.locator('button:has-text("Retake the photo")').count()) === 1);
  await page.screenshot({ path: `${SP}/warn_poor.png` });

  const before = assessCalls.length;
  await extract(`${SP}/clear.jpg`);
  check('clear photo: no warning', (await warning.count()) === 0);
  check('clear photo: quality was checked', assessCalls.length === before + 1);

  const beforePdf = assessCalls.length;
  await extract(`${SP}/clear.pdf`);
  check('PDF: no photo check, no warning', assessCalls.length === beforePdf && (await warning.count()) === 0);

  await extract(`${SP}/poor.jpg`);
  await page.click('button:has-text("Retake the photo")');
  check('retake button returns to the camera flow',
    (await page.locator('[role=tab][aria-selected=true]:has-text("Scan photos")').count()) === 1
    && (await page.locator('text=Extracted Grocery Line Items').count()) === 0);
  await browser.close();
  console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
})().catch((e) => { console.error('SCRIPT ERROR', e); process.exit(1); });
