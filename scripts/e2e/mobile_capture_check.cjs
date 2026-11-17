/**
 * Mobile workflow check for invoice capture (Playwright, Pixel 7 emulation, Chromium fake camera).
 * Exercises: camera permission granted / denied, live capture of several pages, gallery upload,
 * automatic rotation, rotate left/right/180/reset, replace, remove, reorder, PDF download,
 * extraction + original-photo fallback, camera-unavailable fallback, invalid files, server errors.
 *
 * NOT a substitute for a physical Android device: the Capacitor WebView, real camera hardware,
 * Android permission dialogs and the native camera intent are not exercised here.
 *
 * Run (backend on :8000 with a throwaway DATABASE_URL, Vite on :5173):
 *   backend/.venv/bin/python scripts/e2e/prepare_mobile_assets.py /tmp/mobile-e2e
 *   node scripts/e2e/mobile_capture_check.cjs /tmp/mobile-e2e
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const SP = process.argv[2]; // directory with assets from prepare_mobile_assets.py; screenshots are written here
const APP = process.env.APP_URL || 'http://127.0.0.1:5173/scripts/e2e/harness/index.html';
const API = process.env.API_URL || 'http://127.0.0.1:8000/api/v1';
const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok: !!ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`); };
const j = (r) => r.json();

async function token(email) {
  const H = { 'Content-Type': 'application/json' };
  await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) });
  const { access_token } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) }).then(j);
  await fetch(`${API}/shops`, { method: 'POST', headers: { ...H, Authorization: `Bearer ${access_token}` }, body: JSON.stringify({ shop_name: 'Kirana', owner_name: 'R', business_type: 'Grocery/Kirana', location: 'B' }) });
  return access_token;
}
async function openApp(ctx, tok, init) {
  const page = await ctx.newPage();
  page.on('pageerror', (e) => check('no uncaught page errors', false, e.message));
  if (init) await page.addInitScript(init);
  await page.goto(APP);
  await page.evaluate((t) => localStorage.setItem('shoppulse_token', t), tok);
  await page.reload();
  await page.waitForSelector('text=Open camera');
  return page;
}
const pageCount = (page) => page.locator('[aria-label^="Show page"]').count();
async function waitPages(page, n, timeout = 180000) {
  await page.waitForFunction((n) => document.querySelectorAll('[aria-label^="Show page"]').length === n
    && !document.body.innerText.includes('Checking and correcting') && !document.body.innerText.includes('Uploading'), n, { timeout });
}

(async () => {
  const pixel = devices['Pixel 7'];
  if (!process.env.ONLY_C) {
  // ---------------- A: camera granted (fake camera = video of an invoice photo) ----------------
  const browser = await chromium.launch({ args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', `--use-file-for-fake-video-capture=${SP}/cam.y4m`] });
  const tokA = await token(`mobile-a-${Date.now()}@example.com`);
  const ctxA = await browser.newContext({ ...pixel, permissions: ['camera'] });
  const page = await openApp(ctxA, tokA);
  await page.screenshot({ path: `${SP}/m_0_start.png` });
  const tapTarget = await page.locator('button:has-text("Open camera")').boundingBox();
  check('primary capture button is touch-friendly (>= 44 px tall)', tapTarget && tapTarget.height >= 44, `${Math.round(tapTarget?.height)} px`);
  await page.click('button:has-text("Open camera")');
  await page.waitForSelector('[aria-label="Invoice camera"]');
  await page.waitForFunction(() => { const v = document.querySelector('[aria-label="Invoice camera"] video'); return v && v.videoWidth > 0; }, null, { timeout: 20000 });
  const vw = await page.evaluate(() => document.querySelector('[aria-label="Invoice camera"] video').videoWidth);
  check('camera permission granted and live preview starts', vw > 0, `video ${vw}px wide`);
  await page.screenshot({ path: `${SP}/m_1_camera.png` });
  await page.click('[aria-label="Capture page"]');
  await page.waitForTimeout(700);
  await page.click('[aria-label="Capture page"]');
  await page.waitForTimeout(700);
  const counter = await page.locator('[aria-label="Invoice camera"]').innerText();
  check('two pages captured from the camera', /2 pages captured/.test(counter));
  await page.click('[aria-label="Invoice camera"] button:has-text("Done")');
  await waitPages(page, 2);
  check('captured pages processed into reviewable pages', (await pageCount(page)) === 2);

  // Gallery upload, multiple photos at once
  await page.setInputFiles('input[type=file][multiple]', [`${SP}/gallery_p2.jpg`, `${SP}/gallery_p3.jpg`]);
  await waitPages(page, 4);
  check('gallery upload of several photos adds pages in order', (await pageCount(page)) === 4);
  await page.click('[aria-label="Show page 3"]');
  await page.waitForTimeout(800);
  const p3 = await page.locator('text=What was done').locator('..').innerText();
  check('upside-down gallery photo turned upright automatically', /upside down \(180°\)/.test(p3), p3.split('\n')[1]);
  await page.screenshot({ path: `${SP}/m_2_review.png`, fullPage: true });

  // Rotation controls (state read back from the API)
  const imgSrc = async () => page.locator('figure img').last().getAttribute('src');
  const before = await imgSrc();
  await page.click('button:has-text("Rotate right")'); await page.waitForTimeout(1500);
  const afterRight = await imgSrc();
  check('rotate right updates the preview', before !== afterRight);
  const rotText = async () => (await page.locator('text=What was done').locator('..').innerText());
  check('rotate right recorded (90°)', /You turned the page right \(90°\)/.test(await rotText()));
  await page.click('button:has-text("Rotate 180")'); await page.waitForTimeout(1500);
  check('rotate 180 recorded (now 270° = left)', /You turned the page left \(90°\)/.test(await rotText()));
  await page.click('button:has-text("Rotate left")'); await page.waitForTimeout(1500);
  check('rotate left recorded (now 180°)', /upside down \(180°\)\./.test(await rotText()) && /You turned/.test(await rotText()));
  await page.click('button:has-text("Reset")'); await page.waitForTimeout(1500);
  check('reset rotation clears manual rotation', !/You turned/.test(await rotText()));

  // Replace page 2 with another photo, position kept
  await page.click('[aria-label="Show page 2"]'); await page.waitForTimeout(500);
  const oldThumb = await page.locator('[aria-label="Show page 2"] img').getAttribute('src').catch(() => '');
  await page.click('button:has-text("Replace")');
  await page.setInputFiles('input[type=file][multiple]', [`${SP}/gallery_p3.jpg`]);
  await waitPages(page, 4);
  await page.waitForTimeout(1500);
  const newThumb = await page.locator('[aria-label="Show page 2"] img').getAttribute('src').catch(() => '');
  check('replace keeps page count and position', (await pageCount(page)) === 4 && oldThumb !== newThumb);

  // Remove + reorder
  await page.click('[aria-label="Remove page 4"]');
  await page.waitForFunction(() => document.querySelectorAll('[aria-label^="Show page"]').length === 3);
  check('remove page', (await pageCount(page)) === 3);
  const t1 = await page.locator('[aria-label="Show page 1"] img').getAttribute('src');
  await page.click('[aria-label="Move page 2 earlier"]'); await page.waitForTimeout(1500);
  const t1b = await page.locator('[aria-label="Show page 1"] img').getAttribute('src');
  check('reorder pages', t1 !== t1b);

  // PDF
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 60000 }), page.click('button:has-text("Download PDF")')]);
  const pdfPath = `${SP}/m_download.pdf`;
  await dl.saveAs(pdfPath);
  const pdf = fs.readFileSync(pdfPath);
  const pages = (pdf.toString('latin1').match(/\/Type \/Page /g) || []).length;
  check('PDF created with all pages in order', pdf.slice(0, 5).toString() === '%PDF-' && pages === 3, `${pages} pages, ${pdf.length} bytes`);

  // Upload & extraction
  await page.click('button:has-text("Read invoice")');
  await page.waitForSelector('text=Extracted Grocery Line Items', { timeout: 240000 });
  const items = await page.locator('tbody tr').count();
  check('upload + extraction shows the review table', items > 0, `${items} line items`);
  check('prepared-scan banner shown', await page.locator('text=prepared pages').count() > 0);
  await page.screenshot({ path: `${SP}/m_3_results.png`, fullPage: true });
  await page.click('button:has-text("Read the original photos")');
  await page.waitForSelector('text=without corrections', { timeout: 240000 });
  check('fallback to original photos works', true);
  await ctxA.close();
  await browser.close();

  // ---------------- B: permission denied ----------------
  const b2 = await chromium.launch({ args: ['--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${SP}/cam.y4m`] });
  const tokB = await token(`mobile-b-${Date.now()}@example.com`);
  const ctxB = await b2.newContext({ ...pixel, permissions: [] });
  const pB = await openApp(ctxB, tokB, () => {
    navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'));
  });
  await pB.click('button:has-text("Open camera")');
  await pB.waitForSelector('text=Take or choose photos instead', { timeout: 20000 }).catch(() => null);
  const deniedText = await pB.locator('[aria-label="Invoice camera"]').innerText().catch(() => '');
  check('camera permission denied: clear message + photo fallback', /permission was denied/i.test(deniedText) && /choose photos instead/i.test(deniedText));
  await pB.screenshot({ path: `${SP}/m_4_denied.png` });
  const [chooser] = await Promise.all([pB.waitForEvent('filechooser', { timeout: 10000 }).catch(() => null), pB.click('button:has-text("Take or choose photos instead")')]);
  check('fallback opens the phone camera / picker', !!chooser);
  await ctxB.close();
  await b2.close();

  }
  // ---------------- C: no camera API (old WebView / insecure context) ----------------
  const b3 = await chromium.launch();
  const tokC = await token('mobile-c' + Date.now() + '@example.com');
  const ctxC = await b3.newContext({ ...pixel });
  const pC = await openApp(ctxC, tokC, () => { Object.defineProperty(navigator, 'mediaDevices', { value: undefined }); });
  const [chooserC] = await Promise.all([pC.waitForEvent('filechooser', { timeout: 10000 }).catch(() => null), pC.click('button:has-text("Open camera")')]);
  const captureAttr = await pC.locator('input[capture]').getAttribute('capture');
  check('camera unavailable: native camera capture input used instead', !!chooserC && captureAttr === 'environment');

  // Invalid files
  fs.writeFileSync(`${SP}/not_a_photo.pdf`, '%PDF-1.4 fake');
  await pC.setInputFiles('input[type=file][multiple]', [`${SP}/not_a_photo.pdf`]);
  const errC = await pC.locator('[role=alert]').innerText().catch(() => '');
  check('invalid file rejected with a clear message', /is a PDF/.test(errC), errC.slice(0, 80));
  fs.writeFileSync(`${SP}/fake.jpg`, 'this is not really a jpeg at all');
  await pC.setInputFiles('input[type=file][multiple]', [`${SP}/fake.jpg`]);
  await pC.waitForSelector('text=Could not add photo', { timeout: 60000 });
  const cardC = await pC.locator('text=Could not add photo').locator('..').locator('..').innerText();
  check('corrupt image rejected by the server, shown on the page card', /not a supported photo|could not be read/i.test(cardC), cardC.replace(/\n/g, ' ').slice(0, 90));

  // Server / storage error then retry
  let fail = true;
  await pC.route('**/document-prep/sessions/*/pages', async (route) => {
    if (fail) { fail = false; return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'The scanner is busy with other photos. Please try again in a moment.' }) }); }
    return route.continue();
  });
  await pC.click('button:has-text("Remove")');
  await pC.setInputFiles('input[type=file][multiple]', [`${SP}/gallery_p2.jpg`]);
  await pC.waitForSelector('text=scanner is busy', { timeout: 60000 });
  check('server error shown on the page card', true);
  await pC.screenshot({ path: `${SP}/m_5_error.png`, fullPage: true });
  await pC.click('button:has-text("Try again")');
  const okRetry = await pC.waitForFunction(() => document.querySelectorAll('[aria-label^="Show page"]').length === 1, null, { timeout: 300000 }).then(() => true).catch(() => false);
  if (!okRetry) console.log('STATE', (await pC.locator('h3:has-text("Pages")').locator('..').innerText()).split(String.fromCharCode(10)).join(' | '));
  check('retry after server error succeeds', okRetry && (await pageCount(pC)) === 1);
  await ctxC.close();
  await b3.close();

  fs.writeFileSync(`${SP}/mobile_results.json`, JSON.stringify(results, null, 1));
  console.log(`\n${results.filter((r) => r.ok).length}/${results.length} checks passed`);
})().catch((e) => { console.error('SCRIPT ERROR', e); fs.writeFileSync(`${SP}/mobile_results.json`, JSON.stringify(results, null, 1)); process.exit(1); });
