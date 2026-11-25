/**
 * Browser check: Role-based access control for OWNER, MANAGER, and CASHIER.
 * Verifies navigation visibility, route protection, and direct access enforcement
 * using real browser sessions against the isolated test backend and web server.
 *
 * Run through the isolated test launcher:
 *   node scripts/e2e/run.cjs role_access_check
 */
const { chromium } = require('playwright');
const { API, WEB } = require('./e2e_env.cjs').e2eTarget();
const HARNESS = `${WEB}/scripts/e2e/harness/role-nav.html`;

const results = [];
const check = (n, ok, d = '') => {
  results.push(ok);
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${n}${d ? ' — ' + d : ''}`);
};

(async () => {
  const H = { 'Content-Type': 'application/json' };
  const ts = Date.now();

  // 1. Backend Verification: Register Owner & Create Shop
  const ownerEmail = `owner-${ts}@example.com`;
  await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email: ownerEmail, password: 'password123' }) });
  const { access_token: ownerToken } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email: ownerEmail, password: 'password123' }) }).then(r => r.json());
  const ownerH = { ...H, Authorization: `Bearer ${ownerToken}` };

  const shopRes = await fetch(`${API}/shops`, {
    method: 'POST',
    headers: ownerH,
    body: JSON.stringify({ shop_name: 'E2E Role Kirana', owner_name: 'Owner Alice', business_type: 'Grocery/Kirana', location: 'Market St' })
  }).then(r => r.json());
  const shopId = shopRes.id;
  check('Owner created shop on backend', Boolean(shopId), shopId);

  // 2. Setup Manager
  const managerEmail = `manager-${ts}@example.com`;
  const regMgr = await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email: managerEmail, password: 'password123' }) }).then(r => r.json());
  const managerId = regMgr.id;
  await fetch(`${API}/shops/${shopId}/members`, {
    method: 'POST',
    headers: ownerH,
    body: JSON.stringify({ user_id: managerId, role: 'MANAGER' })
  });
  const { access_token: managerToken } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email: managerEmail, password: 'password123' }) }).then(r => r.json());
  check('Manager joined shop with MANAGER role', Boolean(managerToken));

  // 3. Setup Cashier
  const cashierEmail = `cashier-${ts}@example.com`;
  const regCashier = await fetch(`${API}/auth/register`, { method: 'POST', headers: H, body: JSON.stringify({ email: cashierEmail, password: 'password123' }) }).then(r => r.json());
  const cashierId = regCashier.id;
  await fetch(`${API}/shops/${shopId}/members`, {
    method: 'POST',
    headers: ownerH,
    body: JSON.stringify({ user_id: cashierId, role: 'CASHIER' })
  });
  const { access_token: cashierToken } = await fetch(`${API}/auth/login`, { method: 'POST', headers: H, body: JSON.stringify({ email: cashierEmail, password: 'password123' }) }).then(r => r.json());
  check('Cashier joined shop with CASHIER role', Boolean(cashierToken));

  // Launch browser for UI navigation tests
  const browser = await chromium.launch();

  try {
    // -------------------------------------------------------------------------
    // Scenario A: Owner UI check
    // -------------------------------------------------------------------------
    {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      await context.addInitScript((tok) => {
        localStorage.setItem('shoppulse_token', tok);
        localStorage.setItem('shoppulse_role', 'owner');
      }, ownerToken);

      const page = await context.newPage();
      await page.goto(HARNESS);
      await page.waitForSelector('aside[aria-label="Sidebar Navigation"]', { timeout: 10000 });

      const sidebarText = await page.locator('aside[aria-label="Sidebar Navigation"]').textContent();
      check('Owner sees Overview section', sidebarText.includes('Overview'));
      check('Owner sees Sales & Billing section', sidebarText.includes('Sales & Billing'));
      check('Owner sees Inventory section', sidebarText.includes('Inventory'));
      check('Owner sees Tools & Automation section', sidebarText.includes('Tools & Automation'));
      check('Owner sees Settings section', sidebarText.includes('Settings'));
      await context.close();
    }

    // -------------------------------------------------------------------------
    // Scenario B: Manager UI check
    // -------------------------------------------------------------------------
    {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      await context.addInitScript((tok) => {
        localStorage.setItem('shoppulse_token', tok);
        localStorage.setItem('shoppulse_role', 'manager');
      }, managerToken);

      const page = await context.newPage();
      await page.goto(HARNESS);
      await page.waitForSelector('aside[aria-label="Sidebar Navigation"]', { timeout: 10000 });

      const sidebarText = await page.locator('aside[aria-label="Sidebar Navigation"]').textContent();
      check('Manager sees Overview section', sidebarText.includes('Overview'));
      check('Manager sees Sales & Billing section', sidebarText.includes('Sales & Billing'));
      check('Manager sees Inventory section', sidebarText.includes('Inventory'));
      check('Manager sees Tools & Automation section', sidebarText.includes('Tools & Automation'));
      check('Manager sees Settings section', sidebarText.includes('Settings'));
      await context.close();
    }

    // -------------------------------------------------------------------------
    // Scenario C: Cashier UI check
    // -------------------------------------------------------------------------
    {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      await context.addInitScript((tok) => {
        localStorage.setItem('shoppulse_token', tok);
        localStorage.setItem('shoppulse_role', 'cashier');
      }, cashierToken);

      const page = await context.newPage();
      await page.goto(HARNESS);
      await page.waitForSelector('aside[aria-label="Sidebar Navigation"]', { timeout: 10000 });

      const sidebarText = await page.locator('aside[aria-label="Sidebar Navigation"]').textContent();
      check('Cashier navigation has Sales & Billing', sidebarText.includes('Sales & Billing'));
      check('Cashier navigation has Inventory', sidebarText.includes('Inventory'));
      check('Cashier navigation hides Overview', !sidebarText.includes('Overview'));
      check('Cashier navigation hides Tools & Automation', !sidebarText.includes('Tools & Automation'));
      check('Cashier navigation hides Settings', !sidebarText.includes('Settings'));

      // Direct URL / state check: Cashier is on 'dashboard' -> UnauthorizedAccessBanner renders
      const banner = page.locator('[role="alert"]');
      await banner.waitFor({ timeout: 5000 });
      check('Direct access to dashboard shows UnauthorizedAccessBanner [role="alert"]', (await banner.count()) > 0);

      // Click "Return to POS Billing" button in banner
      const returnBtn = banner.locator('button:has-text("Return to POS Billing")');
      await returnBtn.click();
      await page.waitForTimeout(300);

      const pageTitle = await page.locator('#active-page-title').textContent();
      check('Return to POS Billing navigates Cashier to Sales', pageTitle.includes('sales'));
      check('Unauthorized banner removed after returning to permitted route', (await page.locator('[role="alert"]').count()) === 0);

      await context.close();
    }
  } finally {
    await browser.close();
  }

  const failed = results.filter(r => !r).length;
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  if (failed > 0) process.exit(1);
})();
