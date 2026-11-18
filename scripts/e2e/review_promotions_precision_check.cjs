/**
 * Browser check (Phase 3A follow-up): invoice-total banner, three-decimal display and storage,
 * paid + free units confirmed before stock is posted, and the review screen at phone width.
 *
 * The extraction response is fixed (page.route) so the UI behaviour is deterministic; confirmation
 * goes to the real backend. Generic test values only.
 *
 * Run (backend on :8000 with a throwaway DATABASE_URL, Vite on :5173):
 *   node scripts/e2e/review_promotions_precision_check.cjs /tmp/review-e2e
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const SP = process.argv[2] || '.';
const API = process.env.API_URL || 'http://127.0.0.1:8000/api/v1';
const results = [];
const check = (n, ok, d = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? ' — ' + d : ''}`); };

const EXTRACTION = {
  id: 'inv_e2e_promo', supplier_name: 'Generic FMCG Distributors', invoice_number: `E2E-${Date.now()}`, invoice_date: '05/11/2026',
  total_amount: 412.988, total_units: 23, total_items: 2, confidence_score: 90, status: 'needs_review',
  printed_total: 412.988,
  total_reconciliation: { status: 'matched', message: 'Line amounts agree with the printed total ₹412.988.', printed_total: 412.988, lines_total: 412.988 },
  bundle_notes: [],
  items: [
    { id: 'a', product_name: 'E2E Soap 75G', quantity: 11, paid_quantity: 10, free_quantity: 1, unit: 'pcs', purchase_price: 35.0,
      rate: 35.0, mrp: 40.0, amount: 350.0, line_total: 350.0, printed_amount: 350.0, confidence: 95, confidence_level: 'LOW',
      needs_review: true, validation_issues: ["Promotion printed as '10+1': 10 paid + 1 free = 11 units received."],
      suggestions: [], derived_fields: [], is_free_item: false },
    { id: 'b', product_name: 'E2E Butter Cookies 5RS', quantity: 12, unit: 'pcs', purchase_price: 5.249, rate: 5.249, mrp: 5.0,
      amount: 62.988, line_total: 62.988, printed_amount: 62.988, confidence: 95, confidence_level: 'HIGH', needs_review: false,
      validation_issues: [], suggestions: [], derived_fields: [], is_free_item: false, selling_price: 5.0 },
  ],
};

(async () => {
  fs.mkdirSync(SP, { recursive: true });
  const H = { 'Content-Type': 'application/json' };
  const email = `promo-ui-${Date.now()}@example.com`;
  await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) });
  const { access_token: tok } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) }).then((r) => r.json());
  await fetch(`${API}/shops`, { method: 'POST', headers: { ...H, Authorization: `Bearer ${tok}` }, body: JSON.stringify({ shop_name: 'K', owner_name: 'R', business_type: 'Grocery/Kirana', location: 'B' }) });
  const auth = { Authorization: `Bearer ${tok}` };

  const browser = await chromium.launch();
  for (const [label, ctxOpts] of [['desktop', { viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 }], ['phone', { ...devices['Pixel 7'] }]]) {
    const page = await (await browser.newContext(ctxOpts)).newPage();
    let confirmBodies = [];
    page.on('request', (r) => { if (r.url().includes('/invoices/confirm')) confirmBodies.push(JSON.parse(r.postData() || '{}')); });
    await page.route('**/api/v1/invoices/extract', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ ...EXTRACTION, invoice_number: `${EXTRACTION.invoice_number}-${label}` }),
    }));
    await page.goto('http://127.0.0.1:5173/scripts/e2e/harness/index.html');
    await page.evaluate((t) => localStorage.setItem('shoppulse_token', t), tok);
    await page.goto('http://127.0.0.1:5173/scripts/e2e/harness/index.html');
    await page.click('[role=tab]:has-text("Upload PDF or file")');
    await page.setInputFiles('input[type=file]:not([multiple]):not([capture])', { name: 'bill.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 e2e') });
    await page.click('button:has-text("Extract Line Items")');
    await page.waitForSelector('text=Extracted Grocery Line Items', { timeout: 60000 });

    const banner = page.locator('[data-testid="total-reconciliation"]');
    check(`${label}: invoice-total check shown`, (await banner.count()) === 1 && /agree with the printed total/.test(await banner.innerText()));
    check(`${label}: printed 3-decimal amount shown as printed`, (await page.locator('text=₹62.988').count()) >= 1);
    check(`${label}: paid + free breakdown shown`, (await page.locator('text=10 paid + 1 free = 11 received').count()) === 1);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`${label}: page has no horizontal overflow`, overflow <= 1, `overflow ${overflow}px`);

    await page.click('button:has-text("Items to Inventory")');
    await page.waitForTimeout(400);
    check(`${label}: free units need confirmation before posting`, (await page.locator('[data-testid="free-units-confirm"]').count()) === 1 && confirmBodies.length === 0);
    await page.screenshot({ path: `${SP}/promo_${label}.png`, fullPage: false });
    await page.click('button:has-text("Add to stock including free units")');
    await page.waitForSelector('text=Successfully confirmed', { timeout: 60000 });
    const body = confirmBodies[0] || {};
    const soap = (body.items || []).find((i) => i.name === 'E2E Soap 75G') || {};
    const cookies = (body.items || []).find((i) => i.name === 'E2E Butter Cookies 5RS') || {};
    check(`${label}: confirmation sent explicitly with the paid/free breakdown`, body.confirm_free_units === true
      && soap.quantity === 11 && soap.paid_quantity === 10 && soap.free_quantity === 1 && soap.line_amount === 350);
    check(`${label}: printed 3-decimal amount sent unchanged`, cookies.line_amount === 62.988 && cookies.purchase_price === 5.249);
    await page.close();
  }

  const products = (await fetch(`${API}/products?limit=100`, { headers: auth }).then((r) => r.json())).items;
  const soapP = products.find((p) => p.name === 'E2E Soap 75G');
  check('stock: 11 + 11 units received (two confirmations), printed rate kept as cost', soapP && soapP.current_stock === 22 && soapP.purchase_price === 35);
  const purchases = (await fetch(`${API}/purchases`, { headers: auth }).then((r) => r.json())).items;
  check('purchase total stored with 3 decimals', purchases.length === 2 && purchases.every((p) => p.total_amount === 412.988), JSON.stringify(purchases.map((p) => p.total_amount)));
  await browser.close();
  console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
})().catch((e) => { console.error('SCRIPT ERROR', e); process.exit(1); });
