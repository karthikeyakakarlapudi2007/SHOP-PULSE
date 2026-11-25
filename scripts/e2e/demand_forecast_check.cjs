/**
 * Stage 7.3 Browser E2E Verification: Demand Forecasting Dashboard & Insights Integration.
 *
 * Verifies:
 * 1. Real isolated backend + Vite frontend integration for GET /api/v1/insights/demand-forecast.
 * 2. Owner and Manager roles can view Demand Forecast tab, 6 summary cards, table, search, filters, and product detail modal.
 * 3. Cashier role is blocked from viewing Insights / Demand Forecast.
 * 4. Mobile responsive card layout renders cleanly without horizontal overflow.
 *
 * Run via isolated launcher:
 *   node scripts/e2e/run.cjs demand_forecast_check
 */

const { chromium } = require('playwright');
const { e2eTarget } = require('./e2e_env.cjs');

const { API, WEB } = e2eTarget();
const results = [];

function check(name, ok, detail = '') {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
}

(async () => {
  const H = { 'Content-Type': 'application/json' };
  const ts = Date.now();
  const password = 'Password123!';

  // 1. Setup Owner, Manager, Cashier & Shop
  const ownerEmail = `owner.df.${ts}@example.com`;
  const managerEmail = `mgr.df.${ts}@example.com`;
  const cashierEmail = `cashier.df.${ts}@example.com`;

  const ownerReg = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ email: ownerEmail, password }),
  }).then((r) => r.json());
  const ownerLogin = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ email: ownerEmail, password }),
  }).then((r) => r.json());
  const ownerAuth = { ...H, Authorization: `Bearer ${ownerLogin.access_token}` };

  const shop = await fetch(`${API}/shops`, {
    method: 'POST',
    headers: ownerAuth,
    body: JSON.stringify({
      shop_name: 'Annapurna Kirana E2E',
      owner_name: 'Suresh Owner',
      business_type: 'Grocery/Kirana',
      location: 'Hyderabad',
    }),
  }).then((r) => r.json());
  check('Isolated test shop created', Boolean(shop.id), shop.id);

  const mgrReg = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ email: managerEmail, password }),
  }).then((r) => r.json());
  await fetch(`${API}/shops/${shop.id}/members`, {
    method: 'POST',
    headers: ownerAuth,
    body: JSON.stringify({ user_id: mgrReg.id, email: managerEmail, role: 'MANAGER' }),
  });
  const mgrLogin = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ email: managerEmail, password }),
  }).then((r) => r.json());

  const cashierReg = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ email: cashierEmail, password }),
  }).then((r) => r.json());
  await fetch(`${API}/shops/${shop.id}/members`, {
    method: 'POST',
    headers: ownerAuth,
    body: JSON.stringify({ user_id: cashierReg.id, email: cashierEmail, role: 'CASHIER' }),
  });
  const cashierLogin = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: H,
    body: JSON.stringify({ email: cashierEmail, password }),
  }).then((r) => r.json());

  // 2. Seed real products & sales
  const createProd = async (payload) => {
    const res = await fetch(`${API}/products`, {
      method: 'POST',
      headers: ownerAuth,
      body: JSON.stringify(payload),
    });
    return res.json();
  };

  const rice = await createProd({
    name: 'Basmati Rice E2E',
    category: 'Grains',
    selling_price: 120,
    purchase_price: 95,
    mrp: 140,
    unit: 'kg',
    price_basis_quantity: 1,
    price_basis_unit: 'kg',
    current_stock: 10,
    reorder_level: 5,
  });
  const sugar = await createProd({
    name: 'Refined Sugar E2E',
    category: 'Groceries',
    selling_price: 46,
    purchase_price: 38,
    mrp: 52,
    unit: 'kg',
    price_basis_quantity: 1,
    price_basis_unit: 'kg',
    current_stock: 0,
    reorder_level: 8,
  });
  const dal = await createProd({
    name: 'Toor Dal E2E',
    category: 'Pulses',
    selling_price: 150,
    purchase_price: 120,
    mrp: 170,
    unit: 'kg',
    price_basis_quantity: 1,
    price_basis_unit: 'kg',
    current_stock: 20,
    reorder_level: 5,
  });

  // Record 2 sales for Basmati Rice so it enters Tier 2 sparse history
  for (let i = 0; i < 2; i++) {
    await fetch(`${API}/sales`, {
      method: 'POST',
      headers: ownerAuth,
      body: JSON.stringify({
        items: [{ product_id: rice.id, quantity: 2, unit: 'kg' }],
        payment_method: 'cash',
      }),
    });
  }
  check('Seeded 3 grocery products and 2 POS sales', Boolean(rice.id && sugar.id && dal.id));

  const browser = await chromium.launch({ headless: true });

  try {
    // -------------------------------------------------------------------------
    // Scenario 1: Owner Desktop E2E on Insights -> Demand Forecast
    // -------------------------------------------------------------------------
    const ownerProfile = {
      uid: ownerReg.id,
      email: ownerEmail,
      displayName: 'Suresh Owner',
      ownerName: 'Suresh Owner',
      shopName: shop.shop_name,
      shopId: shop.id,
      role: 'owner',
      theme: 'light',
      language: 'en',
    };

    const ownerCtx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    await ownerCtx.addInitScript(({ token, profile }) => {
      localStorage.setItem('shoppulse_token', token);
      localStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shelfora_active_page', 'insights');
      sessionStorage.setItem('shoppulse_active_page', 'insights');
    }, { token: ownerLogin.access_token, profile: ownerProfile });

    const ownerPage = await ownerCtx.newPage();
    await ownerPage.goto(`${WEB}/`);
    await ownerPage.waitForSelector('button[role="tab"]:has-text("Demand Forecast")', { timeout: 15000 });

    const forecastResponsePromise = ownerPage.waitForResponse(
      (res) => res.url().includes('/api/v1/insights/demand-forecast') && res.status() === 200,
      { timeout: 15000 }
    );
    await ownerPage.click('button[role="tab"]:has-text("Demand Forecast")');
    const forecastRes = await forecastResponsePromise;
    const forecastJson = await forecastRes.json();
    check(
      'Owner Demand Forecast API returned 200 with 3 products',
      forecastJson.total_products_analyzed === 3,
      `total=${forecastJson.total_products_analyzed}`
    );

    await ownerPage.waitForSelector('text=Products Analyzed', { timeout: 10000 });
    const pageText = await ownerPage.locator('main').textContent();
    check('Owner sees all 6 summary card labels', (
      pageText.includes('Products Analyzed') &&
      pageText.includes('Sufficient History') &&
      pageText.includes('Sparse History') &&
      pageText.includes('No Sales History') &&
      pageText.includes('At Risk') &&
      pageText.includes('Out of Stock')
    ));
    check('Owner sees seeded products in forecast table', (
      pageText.includes('Basmati Rice E2E') &&
      pageText.includes('Refined Sugar E2E') &&
      pageText.includes('Toor Dal E2E')
    ));
    check('Owner sees OUT OF STOCK and UNKNOWN severities', (
      pageText.includes('OUT OF STOCK') &&
      pageText.includes('UNKNOWN')
    ));

    // Search filter
    await ownerPage.fill('input[aria-label="Search forecast products"]', 'Basmati');
    await ownerPage.waitForTimeout(200);
    const filteredText = await ownerPage.locator('table').textContent();
    check('Product search filters table to Basmati Rice E2E', (
      filteredText.includes('Basmati Rice E2E') && !filteredText.includes('Refined Sugar E2E')
    ));
    await ownerPage.fill('input[aria-label="Search forecast products"]', '');

    // Open product detail modal
    await ownerPage.click('tr[aria-label="Inspect demand forecast for Basmati Rice E2E"]');
    await ownerPage.waitForSelector('div[role="dialog"]', { timeout: 5000 });
    const modalText = await ownerPage.locator('div[role="dialog"]').textContent();
    check('Product detail modal displays tier, sales, assumptions, and warnings', (
      modalText.includes('Basmati Rice E2E') &&
      modalText.includes('Valid Sales Events') &&
      modalText.includes('Model Tier & Forecast Assumptions') &&
      modalText.includes('Provisional Estimate')
    ));
    await ownerPage.click('button[aria-label="Close forecast details"]');
    await ownerCtx.close();

    // -------------------------------------------------------------------------
    // Scenario 2: Owner Mobile Viewport Check (390x844)
    // -------------------------------------------------------------------------
    const mobileCtx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await mobileCtx.addInitScript(({ token, profile }) => {
      localStorage.setItem('shoppulse_token', token);
      localStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shelfora_active_page', 'insights');
      sessionStorage.setItem('shoppulse_active_page', 'insights');
    }, { token: ownerLogin.access_token, profile: ownerProfile });

    const mobilePage = await mobileCtx.newPage();
    await mobilePage.goto(`${WEB}/`);
    await mobilePage.waitForSelector('button[role="tab"]:has-text("Demand Forecast")', { timeout: 15000 });
    await mobilePage.click('button[role="tab"]:has-text("Demand Forecast")');
    await mobilePage.waitForSelector('text=Inspect Details', { timeout: 10000 });
    const hasOverflow = await mobilePage.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 2
    );
    check('Mobile forecast card view renders without horizontal page overflow', !hasOverflow);
    await mobileCtx.close();

    // -------------------------------------------------------------------------
    // Scenario 3: Manager Desktop E2E
    // -------------------------------------------------------------------------
    const mgrProfile = {
      uid: mgrReg.id,
      email: managerEmail,
      displayName: 'Meera Manager',
      ownerName: 'Suresh Owner',
      shopName: shop.shop_name,
      shopId: shop.id,
      role: 'manager',
      theme: 'light',
      language: 'en',
    };
    const mgrCtx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    await mgrCtx.addInitScript(({ token, profile }) => {
      localStorage.setItem('shoppulse_token', token);
      localStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shelfora_active_page', 'insights');
      sessionStorage.setItem('shoppulse_active_page', 'insights');
    }, { token: mgrLogin.access_token, profile: mgrProfile });

    const mgrPage = await mgrCtx.newPage();
    await mgrPage.goto(`${WEB}/`);
    await mgrPage.waitForSelector('button[role="tab"]:has-text("Demand Forecast")', { timeout: 15000 });
    await mgrPage.click('button[role="tab"]:has-text("Demand Forecast")');
    await mgrPage.waitForSelector('text=Basmati Rice E2E', { timeout: 10000 });
    check('Manager role can access Demand Forecast tab and live data', true);
    await mgrCtx.close();

    // -------------------------------------------------------------------------
    // Scenario 4: Cashier RBAC Restriction Check
    // -------------------------------------------------------------------------
    const cashierProfile = {
      uid: cashierReg.id,
      email: cashierEmail,
      displayName: 'Ravi Cashier',
      ownerName: 'Suresh Owner',
      shopName: shop.shop_name,
      shopId: shop.id,
      role: 'cashier',
      theme: 'light',
      language: 'en',
    };
    const cashierCtx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
    await cashierCtx.addInitScript(({ token, profile }) => {
      localStorage.setItem('shoppulse_token', token);
      localStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shoppulse_local_session', JSON.stringify(profile));
      sessionStorage.setItem('shelfora_active_page', 'insights');
      sessionStorage.setItem('shoppulse_active_page', 'insights');
    }, { token: cashierLogin.access_token, profile: cashierProfile });

    const cashierPage = await cashierCtx.newPage();
    await cashierPage.goto(`${WEB}/`);
    await cashierPage.waitForSelector('div[role="alert"]', { timeout: 15000 });
    const cashierText = await cashierPage.locator('main').textContent();
    check('Cashier is blocked from Insights and Demand Forecast', (
      cashierText.includes('Access Restricted') && !cashierText.includes('Basmati Rice E2E')
    ));
    await cashierCtx.close();
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r).length;
  console.log(`\nSummary: ${results.length - failed}/${results.length} checks passed`);
  if (failed > 0) process.exit(1);
})();
