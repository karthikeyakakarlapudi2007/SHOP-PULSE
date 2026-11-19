/**
 * Browser check (Voice-to-Bill final integration): the spoken price is kept from the voice bill to the
 * cart, the displayed total, the sale request and the saved sale, and stock is reduced correctly.
 *
 * "3 tea packets for 100 rupees and 500 g sugar" (catalogue: tea ₹40 / packet, sugar ₹44 / kg):
 * - tea: 3 packets, spoken ₹100.00 (catalogue would be ₹120.00), shown as "Spoken price";
 * - sugar: 500 g sold as 0.5 kg ("said 500 g"), catalogue ₹22.00, corrected by hand to ₹25.00;
 * - cart and "Complete Sale" show ₹125.00; the request carries the agreed unit prices; the backend
 *   saves ₹125.00; stock: tea -3, sugar -0.5 kg.
 * Runs at desktop width and on an emulated Pixel 7, through the real Sales page and voice modal
 * (typed-sentence simulation; the backend voice service is real). Generic test values.
 *
 * Run through the isolated test launcher (test backend, test database, dedicated ports):
 *   node scripts/e2e/run.cjs voice_bill_price_check
 */
const { chromium, devices } = require('playwright');
const fs = require('fs');
const SP = process.argv[2] || '.';
const { API, WEB } = require('./e2e_env.cjs').e2eTarget();
const SALES = `${WEB}/scripts/e2e/harness/sales.html`;
const results = [];
const check = (n, ok, d = '') => { results.push(ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? ' — ' + d : ''}`); };

(async () => {
  fs.mkdirSync(SP, { recursive: true });
  const H = { 'Content-Type': 'application/json' };
  const email = `voice-ui-${Date.now()}@example.com`;
  await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) });
  const { access_token: tok } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email, password: 'password123' }) }).then((r) => r.json());
  const auth = { ...H, Authorization: `Bearer ${tok}` };
  await fetch(`${API}/shops`, { method: 'POST', headers: auth, body: JSON.stringify({ shop_name: 'K', owner_name: 'R', business_type: 'Grocery/Kirana', location: 'B' }) });
  const mk = (name, unit, stock, price) => fetch(`${API}/products`, { method: 'POST', headers: auth,
    body: JSON.stringify({ name, unit, current_stock: stock, selling_price: price, purchase_price: price }) }).then((r) => r.json());
  const tea = await mk('Tea', 'packet', 20, 40);
  const sugar = await mk('Sugar', 'kg', 10, 44);
  const stock = async (p) => (await fetch(`${API}/products/${p.id}`, { headers: auth }).then((r) => r.json())).current_stock;

  const browser = await chromium.launch();
  let expected = { tea: 20, sugar: 10 };
  for (const [label, ctxOpts] of [['desktop', { viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 }], ['phone', { ...devices['Pixel 7'] }]]) {
    const page = await (await browser.newContext(ctxOpts)).newPage();
    await page.addInitScript((t) => localStorage.setItem('shoppulse_token', t), tok);  // token before page scripts
    const saleBodies = [];
    const saleResponses = [];
    page.on('request', (r) => { if (/\/api\/v1\/sales\/?$/.test(new URL(r.url()).pathname) && r.method() === 'POST') saleBodies.push(JSON.parse(r.postData() || '{}')); });
    page.on('response', async (r) => {
      if (/\/api\/v1\/sales\/?$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST') saleResponses.push(await r.json().catch(() => ({})));
    });
    page.on('pageerror', (e) => console.log(`[page error] ${e.message}`));
    await page.goto(SALES);
    await page.locator('button[title="Voice-to-Bill assistant"]').first().waitFor({ timeout: 30000 })
      .catch(async (e) => { await page.screenshot({ path: `${SP}/voice_start_failed_${label}.png` }); console.log((await page.innerText('body')).slice(0, 400)); throw e; });
    await page.locator('button[title="Voice-to-Bill assistant"]').first().click();
    const input = page.locator('input[placeholder^="Type voice sentence"]');
    await input.waitFor({ timeout: 30000 });
    await input.fill('3 tea packets for 100 rupees and 500 g sugar');
    await page.click('button:has-text("Simulate")');
    // Backend result (authoritative): both lines, sugar converted to 0.5 kg
    await page.waitForSelector('input[aria-label="Line total for Sugar"]', { timeout: 30000 });
    const teaTotal = page.locator('input[aria-label="Line total for Tea"]');
    const sugarTotal = page.locator('input[aria-label="Line total for Sugar"]');
    check(`${label}: tea line keeps the spoken ₹100 (not 3 x ₹40)`, (await teaTotal.inputValue()) === '100'
      && (await page.locator('[data-testid="voice-price-source"]:has-text("Spoken price")').count()) === 1);
    const modalText = await page.locator('text=said 500 g').count();
    check(`${label}: 500 g sugar shown as 0.5 kg at the catalogue price`, (await sugarTotal.inputValue()) === '22' && modalText === 1);

    // Manual correction before saving
    await sugarTotal.fill('25');
    await sugarTotal.press('Enter');
    check(`${label}: corrected sugar total kept`, (await sugarTotal.inputValue()) === '25'
      && (await page.locator('[data-testid="voice-price-source"]:has-text("Edited price")').count()) === 1);
    await page.screenshot({ path: `${SP}/voice_bill_${label}.png`, fullPage: false });

    await page.click('button:has-text("Add to Bill")');
    await page.waitForSelector('[data-testid="cart-line"]', { timeout: 15000 });
    const lines = await page.locator('[data-testid="cart-line"]').allInnerTexts();
    const totals = await page.locator('[data-testid="cart-line-total"]').allInnerTexts();
    check(`${label}: cart lines keep the agreed prices`, JSON.stringify(totals) === JSON.stringify(['₹100.00', '₹25.00'])
      && lines[0].includes('Spoken price kept') && lines[1].includes('Corrected price') && lines[1].includes('said 500 g'), JSON.stringify(totals));
    const completeBtn = page.locator('button:has-text("Complete Sale (₹125.00)")').first();
    check(`${label}: bill total ₹125.00 shown before saving`, (await completeBtn.count()) === 1);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(`${label}: no horizontal page overflow`, overflow <= 1, `overflow ${overflow}px`);
    await page.locator('#customer-bill-section').scrollIntoViewIfNeeded().catch(() => {});
    await page.screenshot({ path: `${SP}/voice_cart_${label}.png`, fullPage: false });

    await completeBtn.click();
    await page.waitForFunction(() => document.body.innerText.includes('125'), null, { timeout: 30000 });
    await page.waitForTimeout(800);
    const sent = Object.fromEntries((saleBodies[0]?.items || []).map((i) => [i.product_id, [i.quantity, Number(i.unit_price.toFixed(6))]]));
    check(`${label}: request carries the agreed unit prices and stock quantities`, saleBodies.length === 1
      && JSON.stringify(sent[tea.id]) === JSON.stringify([3, 33.333333]) && JSON.stringify(sent[sugar.id]) === JSON.stringify([0.5, 50]), JSON.stringify(sent));
    check(`${label}: saved sale total ₹125.00 (= displayed)`, saleResponses[0]?.total_amount === 125, JSON.stringify(saleResponses[0]?.total_amount));
    expected = { tea: expected.tea - 3, sugar: Math.round((expected.sugar - 0.5) * 1000) / 1000 };
    const got = { tea: await stock(tea), sugar: await stock(sugar) };
    check(`${label}: stock reduced (tea -3, sugar -0.5 kg)`, JSON.stringify(got) === JSON.stringify(expected), JSON.stringify(got));
    await page.close();
  }
  await browser.close();
  console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
})().catch((e) => { console.error('SCRIPT ERROR', e); process.exit(1); });
