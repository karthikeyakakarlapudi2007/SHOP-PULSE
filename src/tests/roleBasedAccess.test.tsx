import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

class MemoryStorage implements Storage {
  private store: Record<string, string> = {};
  get length(): number {
    return Object.keys(this.store).length;
  }
  clear(): void {
    this.store = {};
  }
  getItem(key: string): string | null {
    return Object.prototype.hasOwnProperty.call(this.store, key) ? this.store[key] : null;
  }
  key(index: number): string | null {
    return Object.keys(this.store)[index] ?? null;
  }
  removeItem(key: string): void {
    delete this.store[key];
  }
  setItem(key: string, value: string): void {
    this.store[key] = String(value);
  }
}

const memorySessionStorage = new MemoryStorage();
const memoryLocalStorage = new MemoryStorage();

if (typeof globalThis.sessionStorage === 'undefined') {
  vi.stubGlobal('sessionStorage', memorySessionStorage);
}
if (typeof globalThis.localStorage === 'undefined') {
  vi.stubGlobal('localStorage', memoryLocalStorage);
}
if (typeof globalThis.window === 'undefined') {
  vi.stubGlobal('window', {
    dispatchEvent: vi.fn(),
    sessionStorage: memorySessionStorage,
    localStorage: memoryLocalStorage,
  });
}
if (typeof globalThis.CustomEvent === 'undefined') {
  vi.stubGlobal('CustomEvent', class { constructor(public type: string) {} });
}

import { AuthContext } from '../context/authContextDef';
import type { AuthContextType } from '../context/AuthContext';
import type { UserProfile, UserRole } from '../types/user';
import { Sidebar } from '../components/Sidebar';
import { BottomNav } from '../components/BottomNav';
import { MobileNavDrawer } from '../components/MobileNavDrawer';
import { UnauthorizedAccessBanner } from '../components/UnauthorizedAccessBanner';
import { normalizeShopRole } from '../hooks/useShopRole';
import { getLocalSession, saveLocalSession } from '../services/authService';
import { LanguageProvider } from '../i18n/LanguageContext';

function createMockAuthContext(role: UserRole = 'owner', loading = false): AuthContextType {
  const mockProfile: UserProfile = {
    uid: 'test_user_id',
    email: 'test@example.com',
    displayName: 'Test User',
    shopName: 'Test Kirana',
    role,
    theme: 'light',
    language: 'en',
    createdAt: new Date().toISOString(),
    lastLogin: new Date().toISOString(),
  };

  return {
    firebaseUser: { uid: 'test_user_id', email: 'test@example.com' } as any,
    userProfile: mockProfile,
    user: mockProfile,
    loading,
    error: null,
    login: vi.fn(),
    loginDemo: vi.fn(),
    loginWithGoogle: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    resetPassword: vi.fn(),
    refreshProfile: vi.fn(),
    updateProfile: vi.fn(),
    setLanguage: vi.fn(),
    setTheme: vi.fn(),
  };
}

describe('Stage 5.3: Role-Based Access Control and Frontend Navigation Security', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  // ---------------------------------------------------------------------------
  // Test 12: Frontend navigation visibility by role
  // ---------------------------------------------------------------------------
  describe('12. Frontend navigation visibility by role', () => {
    it('Owner sees all navigation groups and management routes', () => {
      const ownerAuth = createMockAuthContext('owner');
      const html = renderToStaticMarkup(
        <LanguageProvider>
          <AuthContext.Provider value={ownerAuth}>
            <Sidebar activePage="dashboard" setActivePage={vi.fn()} />
          </AuthContext.Provider>
        </LanguageProvider>
      );

      // Owner must see all primary sections
      expect(html).toContain('Overview');
      expect(html).toContain('Sales &amp; Billing');
      expect(html).toContain('Inventory');
      expect(html).toContain('Tools &amp; Automation');
      expect(html).toContain('Settings');
    });

    it('Manager sees management navigation routes', () => {
      const managerAuth = createMockAuthContext('manager');
      const html = renderToStaticMarkup(
        <LanguageProvider>
          <AuthContext.Provider value={managerAuth}>
            <Sidebar activePage="dashboard" setActivePage={vi.fn()} />
          </AuthContext.Provider>
        </LanguageProvider>
      );

      // Manager must see Overview, Sales, Inventory, Tools (scanner/insights), Settings
      expect(html).toContain('Overview');
      expect(html).toContain('Sales &amp; Billing');
      expect(html).toContain('Inventory');
      expect(html).toContain('Tools &amp; Automation');
      expect(html).toContain('Settings');
    });

    it('Cashier ONLY sees operational routes (Sales and Inventory) - management sections hidden', () => {
      const cashierAuth = createMockAuthContext('cashier');
      const html = renderToStaticMarkup(
        <LanguageProvider>
          <AuthContext.Provider value={cashierAuth}>
            <Sidebar activePage="sales" setActivePage={vi.fn()} />
          </AuthContext.Provider>
        </LanguageProvider>
      );

      // Cashier MUST see Sales & Billing and Inventory
      expect(html).toContain('Sales &amp; Billing');
      expect(html).toContain('Inventory');

      // Cashier MUST NOT see management overview, tools (scanner/insights), or settings
      expect(html).not.toContain('Overview');
      expect(html).not.toContain('Tools &amp; Automation');
      expect(html).not.toContain('Settings');
    });

    it('BottomNav hides management routes from Cashier', () => {
      const cashierAuth = createMockAuthContext('cashier');
      const html = renderToStaticMarkup(
        <LanguageProvider>
          <AuthContext.Provider value={cashierAuth}>
            <BottomNav activePage="sales" setActivePage={vi.fn()} />
          </AuthContext.Provider>
        </LanguageProvider>
      );

      // Operational items present
      expect(html).toContain('Sales');
      expect(html).toContain('Stock');
      // Management items (Dashboard, Insights) excluded from button list
      expect(html).not.toContain('Home');
      expect(html).not.toContain('Insights');
    });

    it('MobileNavDrawer hides management routes from Cashier', () => {
      const cashierAuth = createMockAuthContext('cashier');
      const html = renderToStaticMarkup(
        <LanguageProvider>
          <AuthContext.Provider value={cashierAuth}>
            <MobileNavDrawer
              isOpen={true}
              onClose={vi.fn()}
              activePage="sales"
              setActivePage={vi.fn()}
            />
          </AuthContext.Provider>
        </LanguageProvider>
      );

      expect(html).toContain('Sales &amp; Billing');
      expect(html).toContain('Inventory');
      expect(html).not.toContain('Overview');
      expect(html).not.toContain('Tools &amp; Automation');
      expect(html).not.toContain('Settings');
    });
  });

  // ---------------------------------------------------------------------------
  // Test 13: Direct URL access to unauthorized pages
  // ---------------------------------------------------------------------------
  describe('13. Direct URL access to unauthorized pages', () => {
    it('Renders UnauthorizedAccessBanner when cashier attempts direct access to dashboard', () => {
      const onNavigate = vi.fn();
      const html = renderToStaticMarkup(
        <UnauthorizedAccessBanner
          page="dashboard"
          currentRole="CASHIER"
          onNavigate={onNavigate}
        />
      );

      expect(html).toContain('role="alert"');
      expect(html).toContain('Access Restricted');
      expect(html).toContain('Shop Dashboard');
      expect(html).toContain('CASHIER');
      expect(html).toContain('Return to POS Billing');
    });

    it('Renders UnauthorizedAccessBanner when cashier attempts direct access to insights', () => {
      const html = renderToStaticMarkup(
        <UnauthorizedAccessBanner
          page="insights"
          currentRole="CASHIER"
          onNavigate={vi.fn()}
        />
      );

      expect(html).toContain('role="alert"');
      expect(html).toContain('Access Restricted');
      expect(html).toContain('Analytics &amp; Insights');
    });

    it('Renders UnauthorizedAccessBanner when cashier attempts direct access to scanner', () => {
      const html = renderToStaticMarkup(
        <UnauthorizedAccessBanner
          page="scanner"
          currentRole="CASHIER"
          onNavigate={vi.fn()}
        />
      );

      expect(html).toContain('role="alert"');
      expect(html).toContain('Invoice Intelligence Scanner');
    });
  });

  // ---------------------------------------------------------------------------
  // Test 14: Role persistence after page refresh
  // ---------------------------------------------------------------------------
  describe('14. Role persistence after page refresh', () => {
    it('Persists CASHIER role in sessionStorage and survives simulated page refresh', () => {
      const cashierProfile: UserProfile = {
        uid: 'cashier_user_99',
        email: 'cashier@example.com',
        displayName: 'Store Cashier',
        shopName: 'Balaji Provisions',
        role: 'cashier',
        theme: 'light',
        language: 'en',
        createdAt: '2026-11-23T00:00:00Z',
        lastLogin: '2026-11-23T00:00:00Z',
      };

      // Save to local session
      saveLocalSession(cashierProfile, false);

      // Simulate browser refresh reading session
      const reloaded = getLocalSession();
      expect(reloaded).not.toBeNull();
      expect(reloaded?.role).toBe('cashier');
      expect(normalizeShopRole(reloaded?.role)).toBe('CASHIER');
    });

    it('Normalizes role strings robustly across case and aliases', () => {
      expect(normalizeShopRole('OWNER')).toBe('OWNER');
      expect(normalizeShopRole('owner')).toBe('OWNER');
      expect(normalizeShopRole('MANAGER')).toBe('MANAGER');
      expect(normalizeShopRole('manager')).toBe('MANAGER');
      expect(normalizeShopRole('CASHIER')).toBe('CASHIER');
      expect(normalizeShopRole('cashier')).toBe('CASHIER');
      expect(normalizeShopRole('staff')).toBe('CASHIER');
      expect(normalizeShopRole(undefined)).toBeNull();
      expect(normalizeShopRole(null)).toBeNull();
    });
  });
});
