/**
 * @file demandForecast.ts
 * @description Pure presentation, filtering, sorting, severity, confidence,
 * and error-classification helpers for the Stage 7.3 Demand Forecast dashboard.
 * Never fabricates forecasts; relies strictly on backend-computed values.
 */

import { ApiError } from '../api/client';
import type {
  ConfidenceLevel,
  ForecastStatus,
  ForecastTier,
  ProductDemandForecast,
} from '../api/insights';

export type StockoutSeverity =
  | 'OUT OF STOCK'
  | 'CRITICAL'
  | 'WARNING'
  | 'HEALTHY'
  | 'UNKNOWN';

export interface StockoutSeverityInfo {
  severity: StockoutSeverity;
  label: string;
  description: string;
  badgeClass: string;
  dotClass: string;
  priorityOrder: number;
}

export interface ConfidenceInfo {
  level: ConfidenceLevel;
  label: string;
  explanation: string;
  badgeClass: string;
  rankOrder: number;
}

export interface TierInfo {
  tier: ForecastTier;
  shortLabel: string;
  label: string;
  description: string;
  badgeClass: string;
}

export type ForecastSortField =
  | 'product_name'
  | 'current_stock'
  | 'daily_demand_rate'
  | 'expected_seven_day_demand'
  | 'days_to_stockout'
  | 'recommended_reorder_quantity'
  | 'confidence_level';

export type SortDirection = 'asc' | 'desc';

export interface ForecastFilterOptions {
  searchQuery?: string;
  tierFilter?: ForecastTier | 'ALL';
  statusFilter?: ForecastStatus | 'ALL';
  confidenceFilter?: ConfidenceLevel | 'ALL';
  sortField?: ForecastSortField;
  sortDirection?: SortDirection;
}

export interface ForecastErrorInfo {
  kind: 'unauthorized' | 'forbidden' | 'not_found' | 'validation' | 'offline' | 'server';
  title: string;
  message: string;
  retryable: boolean;
}

const UNAVAILABLE_FORECAST_STATUSES: ReadonlySet<ForecastStatus> = new Set([
  'NEW_PRODUCT_NO_SALES_HISTORY',
  'INSUFFICIENT_HISTORY',
  'UNIT_REVIEW_REQUIRED',
]);

/**
 * Computes visual stockout risk severity strictly from backend forecast fields.
 * Never returns HEALTHY when forecast is unavailable or days_to_stockout is null.
 */
export function getStockoutSeverity(
  forecast: Pick<
    ProductDemandForecast,
    'current_stock' | 'days_to_stockout' | 'forecast_status' | 'daily_demand_rate'
  >
): StockoutSeverityInfo {
  if (
    forecast.current_stock <= 0 ||
    forecast.forecast_status === 'OUT_OF_STOCK'
  ) {
    return {
      severity: 'OUT OF STOCK',
      label: 'OUT OF STOCK',
      description: 'Immediate attention: current stock is depleted.',
      badgeClass: 'bg-[#FDF1EF] text-[#B93838] border border-[#EF806D]/40',
      dotClass: 'bg-[#B93838]',
      priorityOrder: 0,
    };
  }

  if (
    forecast.days_to_stockout === null ||
    forecast.days_to_stockout === undefined ||
    UNAVAILABLE_FORECAST_STATUSES.has(forecast.forecast_status)
  ) {
    return {
      severity: 'UNKNOWN',
      label: 'UNKNOWN',
      description: 'Insufficient sales history or unavailable forecast.',
      badgeClass: 'bg-[#F3EFE3] text-[#5E6C64] border border-[#DDE9DF]',
      dotClass: 'bg-[#5E6C64]',
      priorityOrder: 4,
    };
  }

  if (forecast.days_to_stockout <= 3) {
    return {
      severity: 'CRITICAL',
      label: 'CRITICAL',
      description: 'Expected stockout within 3 days.',
      badgeClass: 'bg-[#FDF1EF] text-[#B93838] border border-[#EF806D]/50',
      dotClass: 'bg-[#EF806D]',
      priorityOrder: 1,
    };
  }

  if (forecast.days_to_stockout <= 7) {
    return {
      severity: 'WARNING',
      label: 'WARNING',
      description: 'Expected stockout within 7 days.',
      badgeClass: 'bg-[#FEF9EB] text-[#A07828] border border-[#D6AE62]/50',
      dotClass: 'bg-[#D6AE62]',
      priorityOrder: 2,
    };
  }

  return {
    severity: 'HEALTHY',
    label: 'HEALTHY',
    description: 'More than 7 days of estimated stock remaining.',
    badgeClass: 'bg-[#E7F3EE] text-[#153D32] border border-[#23866A]/30',
    dotClass: 'bg-[#23866A]',
    priorityOrder: 3,
  };
}

/**
 * Returns non-probabilistic, plain-English explanations for confidence levels.
 */
export function getConfidenceMetadata(level: ConfidenceLevel): ConfidenceInfo {
  switch (level) {
    case 'HIGH':
      return {
        level: 'HIGH',
        label: 'HIGH',
        explanation: 'Based on a stronger recorded sales history.',
        badgeClass: 'bg-[#E7F3EE] text-[#153D32] border border-[#23866A]/30',
        rankOrder: 3,
      };
    case 'MEDIUM':
      return {
        level: 'MEDIUM',
        label: 'MEDIUM',
        explanation: 'Based on a moderate number of recorded sales.',
        badgeClass: 'bg-[#F0F6FB] text-[#3567A8] border border-[#83B8DD]/40',
        rankOrder: 2,
      };
    case 'LOW':
      return {
        level: 'LOW',
        label: 'LOW',
        explanation: 'Initial estimate based on limited sales history.',
        badgeClass: 'bg-[#FEF9EB] text-[#A07828] border border-[#D6AE62]/40',
        rankOrder: 1,
      };
    case 'NONE':
    default:
      return {
        level: 'NONE',
        label: 'NONE',
        explanation: 'No sales history available.',
        badgeClass: 'bg-[#F3EFE3] text-[#5E6C64] border border-[#DDE9DF]',
        rankOrder: 0,
      };
  }
}

export function getForecastTierMetadata(tier: ForecastTier): TierInfo {
  switch (tier) {
    case 'TIER_1_SUFFICIENT':
      return {
        tier,
        shortLabel: 'Tier 1 • Sufficient',
        label: 'Sufficient Sales History (Tier 1)',
        description: 'EWMA daily demand model across continuous calendar days.',
        badgeClass: 'bg-[#E7F3EE] text-[#153D32] border border-[#23866A]/25',
      };
    case 'TIER_2_SPARSE':
      return {
        tier,
        shortLabel: 'Tier 2 • Sparse',
        label: 'Sparse Sales History (Tier 2)',
        description: 'Conservative linear run-rate based on limited sales.',
        badgeClass: 'bg-[#FEF9EB] text-[#A07828] border border-[#D6AE62]/35',
      };
    case 'TIER_3_COLD_START':
    default:
      return {
        tier: 'TIER_3_COLD_START',
        shortLabel: 'Tier 3 • No Sales',
        label: 'Cold Start / No Sales History (Tier 3)',
        description: 'No recorded sales events; demand is not fabricated.',
        badgeClass: 'bg-[#F3EFE3] text-[#5E6C64] border border-[#DDE9DF]',
      };
  }
}

export function getForecastStatusLabel(status: ForecastStatus): string {
  switch (status) {
    case 'ACTIVE':
      return 'Active Forecast';
    case 'OUT_OF_STOCK':
      return 'Out of Stock';
    case 'LOW_STOCK':
      return 'Low Stock Risk';
    case 'SPARSE_HISTORY':
      return 'Sparse History';
    case 'NEW_PRODUCT_NO_SALES_HISTORY':
      return 'No Sales History';
    case 'UNIT_REVIEW_REQUIRED':
      return 'Unit Review Required';
    case 'INSUFFICIENT_HISTORY':
      return 'Insufficient History';
    default:
      return status;
  }
}

export function formatForecastNumber(
  value: number | null | undefined,
  decimals: number = 2
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  const factor = Math.pow(10, decimals);
  const rounded = Math.round(value * factor) / factor;
  return rounded.toLocaleString('en-IN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

/**
 * Pure filtering and sorting helper for forecast rows.
 */
export function filterAndSortForecasts(
  forecasts: ProductDemandForecast[],
  options: ForecastFilterOptions = {}
): ProductDemandForecast[] {
  const {
    searchQuery = '',
    tierFilter = 'ALL',
    statusFilter = 'ALL',
    confidenceFilter = 'ALL',
    sortField = 'days_to_stockout',
    sortDirection = 'asc',
  } = options;

  const trimmedQuery = searchQuery.trim().toLowerCase();

  const filtered = forecasts.filter((item) => {
    if (trimmedQuery && !item.product_name.toLowerCase().includes(trimmedQuery)) {
      return false;
    }
    if (tierFilter !== 'ALL' && item.forecast_tier !== tierFilter) {
      return false;
    }
    if (statusFilter !== 'ALL' && item.forecast_status !== statusFilter) {
      return false;
    }
    if (confidenceFilter !== 'ALL' && item.confidence_level !== confidenceFilter) {
      return false;
    }
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    const dir = sortDirection === 'asc' ? 1 : -1;

    if (sortField === 'product_name') {
      return a.product_name.localeCompare(b.product_name) * dir;
    }

    if (sortField === 'confidence_level') {
      const rankA = getConfidenceMetadata(a.confidence_level).rankOrder;
      const rankB = getConfidenceMetadata(b.confidence_level).rankOrder;
      if (rankA !== rankB) return (rankA - rankB) * dir;
      return a.product_name.localeCompare(b.product_name);
    }

    const valA = a[sortField];
    const valB = b[sortField];

    // Keep null/unavailable values at the bottom regardless of sort direction
    if (valA === null && valB === null) {
      return a.product_name.localeCompare(b.product_name);
    }
    if (valA === null) return 1;
    if (valB === null) return -1;

    if (valA !== valB) {
      return (Number(valA) - Number(valB)) * dir;
    }
    return a.product_name.localeCompare(b.product_name);
  });

  return sorted;
}

/**
 * Classifies API / network failures cleanly without falling back to demo data.
 */
export function classifyForecastApiError(err: unknown): ForecastErrorInfo {
  const isOffline =
    typeof navigator !== 'undefined' && navigator.onLine === false;

  if (isOffline) {
    return {
      kind: 'offline',
      title: 'You Appear to Be Offline',
      message:
        'Cannot load demand forecasts without a network connection. Reconnect and retry to fetch live store data.',
      retryable: true,
    };
  }

  if (err instanceof ApiError || (err && typeof err === 'object' && 'status' in err)) {
    const apiErr = err as ApiError;
    if (apiErr.status === 401) {
      return {
        kind: 'unauthorized',
        title: 'Authentication Required',
        message:
          apiErr.message ||
          'Your session has expired or you are not signed in. Please sign in again to view demand forecasts.',
        retryable: false,
      };
    }
    if (apiErr.status === 403) {
      return {
        kind: 'forbidden',
        title: 'Access Restricted',
        message:
          apiErr.message ||
          'Demand forecasting insights are restricted to Shop Owner and Manager roles.',
        retryable: false,
      };
    }
    if (apiErr.status === 404) {
      return {
        kind: 'not_found',
        title: 'Forecast Target Not Found',
        message:
          apiErr.message ||
          'The requested shop or product could not be found in your active store.',
        retryable: true,
      };
    }
    if (apiErr.status === 422 || apiErr.status === 400) {
      return {
        kind: 'validation',
        title: 'Invalid Forecast Parameters',
        message:
          apiErr.message ||
          'One or more filter parameters were rejected by the server. Reset filters and try again.',
        retryable: true,
      };
    }
    if (apiErr.status === 0) {
      return {
        kind: 'offline',
        title: 'Backend Unreachable',
        message:
          apiErr.message ||
          'Unable to reach the ShopPulse backend server. Please check your connection or server status.',
        retryable: true,
      };
    }
    return {
      kind: 'server',
      title: 'Unable to Load Demand Forecasts',
      message:
        apiErr.message || 'An unexpected server error occurred while computing forecasts.',
      retryable: true,
    };
  }

  const msg = err instanceof Error ? err.message : 'Failed to load demand forecast data.';
  return {
    kind: 'server',
    title: 'Unable to Load Demand Forecasts',
    message: msg,
    retryable: true,
  };
}
