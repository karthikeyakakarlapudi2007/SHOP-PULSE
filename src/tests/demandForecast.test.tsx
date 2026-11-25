import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ApiError } from '../api/client';
import {
  insightsApi,
  type ProductDemandForecast,
  type ShopForecastSummary,
} from '../api/insights';
import {
  classifyForecastApiError,
  filterAndSortForecasts,
  getConfidenceMetadata,
  getStockoutSeverity,
} from '../utils/demandForecast';
import {
  DemandForecastSection,
  DemandForecastView,
  type DemandForecastViewProps,
} from '../components/DemandForecastSection';
import { ProductForecastDetailModal } from '../components/ProductForecastDetailModal';
import { Insights } from '../pages/Insights';
import { AuthContext } from '../context/authContextDef';
import type { AuthContextType } from '../context/AuthContext';
import type { UserProfile, UserRole } from '../types/user';
import { LanguageProvider } from '../i18n/LanguageContext';

const sampleForecasts: ProductDemandForecast[] = [
  {
    product_id: 'prod-1',
    product_name: 'Basmati Rice 1kg',
    current_stock: 4,
    normalized_unit: 'kg',
    total_valid_sales: 24,
    observable_days: 30,
    daily_demand_rate: 2.0,
    expected_seven_day_demand: 14.0,
    days_to_stockout: 2.0,
    recommended_reorder_quantity: 12.0,
    confidence_level: 'HIGH',
    forecast_tier: 'TIER_1_SUFFICIENT',
    forecast_status: 'LOW_STOCK',
    is_reorder_provisional: false,
    assumptions: ['Calculated using calendar-day EWMA (alpha=0.3) over 30 observable days.'],
    warnings: ['Stockout risk within 7 days (2.0 days remaining).'],
  },
  {
    product_id: 'prod-2',
    product_name: 'Refined Sugar 1kg',
    current_stock: 10,
    normalized_unit: 'kg',
    total_valid_sales: 10,
    observable_days: 20,
    daily_demand_rate: 1.5,
    expected_seven_day_demand: 10.5,
    days_to_stockout: 6.7,
    recommended_reorder_quantity: 4.5,
    confidence_level: 'MEDIUM',
    forecast_tier: 'TIER_1_SUFFICIENT',
    forecast_status: 'LOW_STOCK',
    is_reorder_provisional: true,
    assumptions: ['Safety stock provisionally derived from configured reorder_level (10 kg).'],
    warnings: ['Stockout risk within 7 days (6.7 days remaining).'],
  },
  {
    product_id: 'prod-3',
    product_name: 'Sunflower Oil 1L',
    current_stock: 25,
    normalized_unit: 'L',
    total_valid_sales: 3,
    observable_days: 10,
    daily_demand_rate: 0.5,
    expected_seven_day_demand: 3.5,
    days_to_stockout: 50.0,
    recommended_reorder_quantity: 0,
    confidence_level: 'LOW',
    forecast_tier: 'TIER_2_SPARSE',
    forecast_status: 'SPARSE_HISTORY',
    is_reorder_provisional: true,
    assumptions: ['Initial estimate based on limited sales history (3 sales events over 10 calendar days).'],
    warnings: ['Sparse sales history. Forecast has high uncertainty and is advisory only.'],
  },
  {
    product_id: 'prod-4',
    product_name: 'Toned Milk 500ml',
    current_stock: 0,
    normalized_unit: 'packet',
    total_valid_sales: 0,
    observable_days: 5,
    daily_demand_rate: 0,
    expected_seven_day_demand: 0,
    days_to_stockout: 0,
    recommended_reorder_quantity: 5,
    confidence_level: 'NONE',
    forecast_tier: 'TIER_3_COLD_START',
    forecast_status: 'OUT_OF_STOCK',
    is_reorder_provisional: true,
    assumptions: ['Product has no recorded sales transactions. Category demand is never fabricated.'],
    warnings: ['No sales history recorded for this product.', 'Product is currently out of stock.'],
  },
  {
    product_id: 'prod-5',
    product_name: 'Cardamom Green 50g',
    current_stock: 18,
    normalized_unit: 'packet',
    total_valid_sales: 0,
    observable_days: 14,
    daily_demand_rate: 0,
    expected_seven_day_demand: 0,
    days_to_stockout: null,
    recommended_reorder_quantity: null,
    confidence_level: 'NONE',
    forecast_tier: 'TIER_3_COLD_START',
    forecast_status: 'NEW_PRODUCT_NO_SALES_HISTORY',
    is_reorder_provisional: true,
    assumptions: ['Product has no recorded sales transactions. Category demand is never fabricated.'],
    warnings: ['No sales history recorded for this product.'],
  },
];

const sampleSummary: ShopForecastSummary = {
  shop_id: 'shop-alpha',
  generated_at: '2026-11-24T18:00:00Z',
  total_products_analyzed: 5,
  tier_1_count: 2,
  tier_2_count: 1,
  tier_3_count: 2,
  out_of_stock_count: 1,
  at_risk_stockout_7d_count: 2,
  forecasts: sampleForecasts,
};

function makeBaseViewProps(overrides: Partial<DemandForecastViewProps> = {}): DemandForecastViewProps {
  return {
    summary: sampleSummary,
    loading: false,
    refreshing: false,
    errorInfo: null,
    searchQuery: '',
    tierFilter: 'ALL',
    statusFilter: 'ALL',
    confidenceFilter: 'ALL',
    leadTimeDays: 3,
    sortField: 'days_to_stockout',
    sortDirection: 'asc',
    selectedProduct: null,
    isRestricted: false,
    userRole: 'OWNER',
    onSearchChange: vi.fn(),
    onTierFilterChange: vi.fn(),
    onStatusFilterChange: vi.fn(),
    onConfidenceFilterChange: vi.fn(),
    onLeadTimeChange: vi.fn(),
    onSortChange: vi.fn(),
    onSelectProduct: vi.fn(),
    onClearFilters: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  };
}

function createAuthContext(role: UserRole): AuthContextType {
  const profile: UserProfile = {
    uid: 'user-1',
    email: `${role}@shoppulse.test`,
    displayName: `Test ${role}`,
    shopName: 'Kirana Store',
    role,
    theme: 'light',
    language: 'en',
    createdAt: new Date().toISOString(),
    lastLogin: new Date().toISOString(),
  };

  return {
    firebaseUser: { uid: 'user-1', email: profile.email } as any,
    userProfile: profile,
    user: profile,
    loading: false,
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

describe('Stage 7.3: Demand Forecasting Dashboard & Insights Integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // 1. API Integration check
  it('calls GET /api/v1/insights/demand-forecast with typed query params', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => sampleSummary,
    });
    vi.stubGlobal('fetch', fetchMock);

    const res = await insightsApi.getDemandForecast({
      forecast_tier: 'TIER_1_SUFFICIENT',
      confidence_level: 'HIGH',
      lead_time_days: 5,
    });

    expect(res.total_products_analyzed).toBe(5);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = String(fetchMock.mock.calls[0][0]);
    expect(calledUrl).toContain('/api/v1/insights/demand-forecast');
    expect(calledUrl).toContain('forecast_tier=TIER_1_SUFFICIENT');
    expect(calledUrl).toContain('confidence_level=HIGH');
    expect(calledUrl).toContain('lead_time_days=5');
  });

  // 2. Summary cards & Table rendering
  it('renders all 6 summary cards and forecast table columns for a successful response', () => {
    const html = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps()} />
    );

    // 6 Summary Cards
    expect(html).toContain('Products Analyzed');
    expect(html).toContain('Sufficient History');
    expect(html).toContain('Sparse History');
    expect(html).toContain('No Sales History');
    expect(html).toContain('At Risk (≤ 7 Days)');
    expect(html).toContain('Out of Stock');

    // Table headers
    expect(html).toContain('Product Name');
    expect(html).toContain('Stock');
    expect(html).toContain('Unit');
    expect(html).toContain('Daily Demand');
    expect(html).toContain('7-Day Demand');
    expect(html).toContain('Days to Stockout');
    expect(html).toContain('Reorder Qty');
    expect(html).toContain('Confidence');
    expect(html).toContain('Status');

    // Product rows
    expect(html).toContain('Basmati Rice 1kg');
    expect(html).toContain('Refined Sugar 1kg');
    expect(html).toContain('Sunflower Oil 1L');
    expect(html).toContain('Toned Milk 500ml');
    expect(html).toContain('Cardamom Green 50g');

    // Advisory notice
    expect(html).toContain('Advisory Forecasts Only');
  });

  // 3. Stockout severity classification
  it('classifies stockout severities accurately and never shows HEALTHY when forecast is unavailable', () => {
    expect(getStockoutSeverity(sampleForecasts[3]).severity).toBe('OUT OF STOCK');
    expect(getStockoutSeverity(sampleForecasts[0]).severity).toBe('CRITICAL');
    expect(getStockoutSeverity(sampleForecasts[1]).severity).toBe('WARNING');
    expect(getStockoutSeverity(sampleForecasts[2]).severity).toBe('HEALTHY');
    expect(getStockoutSeverity(sampleForecasts[4]).severity).toBe('UNKNOWN');

    // Ensure unavailable status with non-null days still maps to UNKNOWN
    expect(
      getStockoutSeverity({
        current_stock: 20,
        days_to_stockout: 30,
        forecast_status: 'UNIT_REVIEW_REQUIRED',
        daily_demand_rate: 0.5,
      }).severity
    ).toBe('UNKNOWN');
  });

  // 4. Confidence explanations
  it('renders plain-English, non-probabilistic confidence explanations', () => {
    expect(getConfidenceMetadata('HIGH').explanation).toBe(
      'Based on a stronger recorded sales history.'
    );
    expect(getConfidenceMetadata('MEDIUM').explanation).toBe(
      'Based on a moderate number of recorded sales.'
    );
    expect(getConfidenceMetadata('LOW').explanation).toBe(
      'Initial estimate based on limited sales history.'
    );
    expect(getConfidenceMetadata('NONE').explanation).toBe(
      'No sales history available.'
    );

    const html = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps()} />
    );
    expect(html).toContain('Based on a stronger recorded sales history.');
    expect(html).toContain('Initial estimate based on limited sales history.');
    expect(html).toContain('No sales history available.');
  });

  // 5. Search & Filters
  it('filters forecasts by product search, tier, status, and confidence', () => {
    const bySearch = filterAndSortForecasts(sampleForecasts, { searchQuery: 'rice' });
    expect(bySearch.map((f) => f.product_id)).toEqual(['prod-1']);

    const byTier = filterAndSortForecasts(sampleForecasts, {
      tierFilter: 'TIER_2_SPARSE',
    });
    expect(byTier.map((f) => f.product_id)).toEqual(['prod-3']);

    const byConfidence = filterAndSortForecasts(sampleForecasts, {
      confidenceFilter: 'MEDIUM',
    });
    expect(byConfidence.map((f) => f.product_id)).toEqual(['prod-2']);

    const byStatus = filterAndSortForecasts(sampleForecasts, {
      statusFilter: 'NEW_PRODUCT_NO_SALES_HISTORY',
    });
    expect(byStatus.map((f) => f.product_id)).toEqual(['prod-5']);

    // Rendered filtered empty state with Clear All Filters button
    const noMatchHtml = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps({ searchQuery: 'Nonexistent Item' })} />
    );
    expect(noMatchHtml).toContain('No product forecasts match your active search or filter criteria.');
    expect(noMatchHtml).toContain('Clear All Filters');
  });

  // 6. Sorting (including nulls-last behavior)
  it('sorts columns cleanly and keeps unavailable/null metrics at the end', () => {
    const byDaysAsc = filterAndSortForecasts(sampleForecasts, {
      sortField: 'days_to_stockout',
      sortDirection: 'asc',
    });
    expect(byDaysAsc.map((f) => f.product_id)).toEqual([
      'prod-4', // 0
      'prod-1', // 2.0
      'prod-2', // 6.7
      'prod-3', // 50.0
      'prod-5', // null last
    ]);

    const byDaysDesc = filterAndSortForecasts(sampleForecasts, {
      sortField: 'days_to_stockout',
      sortDirection: 'desc',
    });
    expect(byDaysDesc.map((f) => f.product_id)).toEqual([
      'prod-3', // 50.0
      'prod-2', // 6.7
      'prod-1', // 2.0
      'prod-4', // 0
      'prod-5', // null still last
    ]);

    const byName = filterAndSortForecasts(sampleForecasts, {
      sortField: 'product_name',
      sortDirection: 'asc',
    });
    expect(byName[0].product_name).toBe('Basmati Rice 1kg');
  });

  // 7. Cold-start & Sparse-history states
  it('displays explicit all-cold-start banner and sparse-history disclosures', () => {
    const allColdSummary: ShopForecastSummary = {
      shop_id: 'shop-cold',
      generated_at: '2026-11-24T18:00:00Z',
      total_products_analyzed: 1,
      tier_1_count: 0,
      tier_2_count: 0,
      tier_3_count: 1,
      out_of_stock_count: 0,
      at_risk_stockout_7d_count: 0,
      forecasts: [sampleForecasts[4]],
    };

    const html = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps({ summary: allColdSummary })} />
    );
    expect(html).toContain('No Recorded Sales History Yet');
    expect(html).toContain('does not fabricate category-based demand');
    expect(html).toContain('UNKNOWN');

    const sparseHtml = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps({ tierFilter: 'TIER_2_SPARSE' })} />
    );
    expect(sparseHtml).toContain('Tier 2 • Sparse');
    expect(sparseHtml).toContain('Sunflower Oil 1L');
  });

  // 8. Provisional reorder disclosure & Product detail modal
  it('renders provisional reorder disclosure and product detail modal with assumptions and warnings', () => {
    const tableHtml = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps()} />
    );
    expect(tableHtml).toContain('Provisional');

    const modalHtml = renderToStaticMarkup(
      <ProductForecastDetailModal
        forecast={sampleForecasts[1]}
        leadTimeDays={5}
        onClose={vi.fn()}
      />
    );
    expect(modalHtml).toContain('Refined Sugar 1kg');
    expect(modalHtml).toContain('Provisional Estimate');
    expect(modalHtml).toContain('Provisional safety-stock disclosure');
    expect(modalHtml).toContain('reorder_level');
    expect(modalHtml).toContain('5 days');
    expect(modalHtml).toContain('Warnings &amp; Uncertainty Notices');
    expect(modalHtml).toContain('Model Tier &amp; Forecast Assumptions');
    expect(modalHtml).toContain('Stockout risk within 7 days (6.7 days remaining).');
    expect(modalHtml).toContain('Over 20 observable days');
  });

  // 9. Empty catalog & Loading skeleton states
  it('renders empty product catalog state and loading skeleton', () => {
    const emptySummary: ShopForecastSummary = {
      shop_id: 'shop-empty',
      generated_at: '2026-11-24T18:00:00Z',
      total_products_analyzed: 0,
      tier_1_count: 0,
      tier_2_count: 0,
      tier_3_count: 0,
      out_of_stock_count: 0,
      at_risk_stockout_7d_count: 0,
      forecasts: [],
    };

    const emptyHtml = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps({ summary: emptySummary })} />
    );
    expect(emptyHtml).toContain('Empty Product Catalog');
    expect(emptyHtml).toContain('Your active catalog has no products yet.');

    const loadingHtml = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps({ summary: null, loading: true })} />
    );
    expect(loadingHtml).toContain('Loading demand forecasts');
    expect(loadingHtml).toContain('animate-pulse');
  });

  // 10. API error classification & UI error states (401, 403, 422, offline)
  it('renders error, unauthorized, and offline states without substituting demo data', () => {
    const unauthorizedInfo = classifyForecastApiError(
      new ApiError('Session expired', 401, null, 'AUTHENTICATION_ERROR')
    );
    expect(unauthorizedInfo.kind).toBe('unauthorized');

    const forbiddenInfo = classifyForecastApiError(
      new ApiError('Cashier blocked', 403, null, 'AUTHORIZATION_FORBIDDEN')
    );
    expect(forbiddenInfo.kind).toBe('forbidden');

    const validationInfo = classifyForecastApiError(
      new ApiError('Invalid tier', 422, null, 'VALIDATION_OR_CLIENT_ERROR')
    );
    expect(validationInfo.kind).toBe('validation');

    const offlineInfo = classifyForecastApiError(
      new ApiError('Network down', 0, null, 'NETWORK_OR_CORS_FAILURE')
    );
    expect(offlineInfo.kind).toBe('offline');
    expect(offlineInfo.retryable).toBe(true);

    const errHtml = renderToStaticMarkup(
      <DemandForecastView
        {...makeBaseViewProps({ summary: null, errorInfo: offlineInfo })}
      />
    );
    expect(errHtml).toContain('Backend Unreachable');
    expect(errHtml).toContain('Retry Loading Forecasts');
    expect(errHtml).not.toContain('Basmati Rice 1kg');
  });

  // 11. Role-based UI gating (OWNER, MANAGER, CASHIER)
  it('enforces role-based UI access for Owner, Manager, and Cashier', () => {
    const ownerAuth = createAuthContext('owner');
    const managerAuth = createAuthContext('manager');
    const cashierAuth = createAuthContext('cashier');

    const ownerInsightsHtml = renderToStaticMarkup(
      <LanguageProvider>
        <AuthContext.Provider value={ownerAuth}>
          <Insights />
        </AuthContext.Provider>
      </LanguageProvider>
    );
    expect(ownerInsightsHtml).toContain('Demand Forecast');

    const managerInsightsHtml = renderToStaticMarkup(
      <LanguageProvider>
        <AuthContext.Provider value={managerAuth}>
          <Insights />
        </AuthContext.Provider>
      </LanguageProvider>
    );
    expect(managerInsightsHtml).toContain('Demand Forecast');

    const cashierInsightsHtml = renderToStaticMarkup(
      <LanguageProvider>
        <AuthContext.Provider value={cashierAuth}>
          <Insights />
        </AuthContext.Provider>
      </LanguageProvider>
    );
    expect(cashierInsightsHtml).toContain('Access Restricted');
    expect(cashierInsightsHtml).not.toContain('Demand Forecast');

    const cashierSectionHtml = renderToStaticMarkup(
      <AuthContext.Provider value={cashierAuth}>
        <DemandForecastSection />
      </AuthContext.Provider>
    );
    expect(cashierSectionHtml).toContain('Access Restricted');
    expect(cashierSectionHtml).not.toContain('Products Analyzed');
  });

  // 12. Mobile responsiveness markup verification
  it('renders both desktop responsive table and mobile card layout containers', () => {
    const html = renderToStaticMarkup(
      <DemandForecastView {...makeBaseViewProps()} />
    );

    expect(html).toContain('hidden md:block overflow-x-auto');
    expect(html).toContain('md:hidden space-y-3');
    expect(html).toContain('Inspect Details');
  });
});
