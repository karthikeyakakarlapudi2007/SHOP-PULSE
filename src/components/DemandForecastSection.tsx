import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Package,
  AlertTriangle,
  AlertCircle,
  Search,
  RefreshCw,
  ArrowUpDown,
  ChevronRight,
  ShieldAlert,
  WifiOff,
  Lock,
  Info,
  Activity,
  Sparkles,
  Filter,
} from 'lucide-react';
import { Card } from './Card';
import { ProductForecastDetailModal } from './ProductForecastDetailModal';
import {
  insightsApi,
  type ConfidenceLevel,
  type ForecastStatus,
  type ForecastTier,
  type ProductDemandForecast,
  type ShopForecastSummary,
} from '../api/insights';
import { useShopRole } from '../hooks/useShopRole';
import {
  classifyForecastApiError,
  filterAndSortForecasts,
  formatForecastNumber,
  getConfidenceMetadata,
  getForecastStatusLabel,
  getForecastTierMetadata,
  getStockoutSeverity,
  type ForecastErrorInfo,
  type ForecastSortField,
  type SortDirection,
} from '../utils/demandForecast';

export interface DemandForecastViewProps {
  summary: ShopForecastSummary | null;
  loading: boolean;
  refreshing?: boolean;
  errorInfo: ForecastErrorInfo | null;
  searchQuery: string;
  tierFilter: ForecastTier | 'ALL';
  statusFilter: ForecastStatus | 'ALL';
  confidenceFilter: ConfidenceLevel | 'ALL';
  leadTimeDays: number;
  sortField: ForecastSortField;
  sortDirection: SortDirection;
  selectedProduct: ProductDemandForecast | null;
  isRestricted?: boolean;
  userRole?: string | null;
  onSearchChange: (q: string) => void;
  onTierFilterChange: (tier: ForecastTier | 'ALL') => void;
  onStatusFilterChange: (status: ForecastStatus | 'ALL') => void;
  onConfidenceFilterChange: (confidence: ConfidenceLevel | 'ALL') => void;
  onLeadTimeChange: (days: number) => void;
  onSortChange: (field: ForecastSortField) => void;
  onSelectProduct: (product: ProductDemandForecast | null) => void;
  onClearFilters: () => void;
  onRetry: () => void;
}

export const DemandForecastView: React.FC<DemandForecastViewProps> = ({
  summary,
  loading,
  refreshing = false,
  errorInfo,
  searchQuery,
  tierFilter,
  statusFilter,
  confidenceFilter,
  leadTimeDays,
  sortField,
  sortDirection,
  selectedProduct,
  isRestricted = false,
  userRole = null,
  onSearchChange,
  onTierFilterChange,
  onStatusFilterChange,
  onConfidenceFilterChange,
  onLeadTimeChange,
  onSortChange,
  onSelectProduct,
  onClearFilters,
  onRetry,
}) => {
  const visibleForecasts = useMemo(() => {
    if (!summary?.forecasts) return [];
    return filterAndSortForecasts(summary.forecasts, {
      searchQuery,
      tierFilter,
      statusFilter,
      confidenceFilter,
      sortField,
      sortDirection,
    });
  }, [
    summary,
    searchQuery,
    tierFilter,
    statusFilter,
    confidenceFilter,
    sortField,
    sortDirection,
  ]);

  const hasActiveFilters =
    searchQuery.trim() !== '' ||
    tierFilter !== 'ALL' ||
    statusFilter !== 'ALL' ||
    confidenceFilter !== 'ALL';

  // 1. Role-Based UI Restriction State
  if (isRestricted) {
    return (
      <div
        role="alert"
        className="bg-white rounded-2xl border border-[#EF806D]/40 p-6 sm:p-8 text-center max-w-xl mx-auto my-4 shadow-xs"
      >
        <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-[#FDF1EF] text-[#B93838] flex items-center justify-center">
          <Lock className="w-6 h-6" />
        </div>
        <h3 className="text-base font-extrabold text-[#153D32]">
          Access Restricted
        </h3>
        <p className="text-xs sm:text-sm text-[#5E6C64] mt-1.5 leading-relaxed">
          Demand forecasting and inventory replenishment intelligence are available only to{' '}
          <strong className="text-[#153D32]">Shop Owner</strong> and{' '}
          <strong className="text-[#153D32]">Manager</strong> roles.
          {userRole ? ` Current role: ${userRole}.` : ''}
        </p>
      </div>
    );
  }

  // 2. Loading Skeleton State
  if (loading && !summary) {
    return (
      <div
        role="status"
        aria-label="Loading demand forecasts"
        className="space-y-6 animate-pulse"
      >
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {Array.from({ length: 6 }).map((_, idx) => (
            <div
              key={idx}
              className="bg-white p-4 rounded-2xl border border-[#DDE9DF] h-24 space-y-2"
            >
              <div className="h-3 w-24 bg-[#F3EFE3] rounded" />
              <div className="h-6 w-12 bg-[#DDE9DF]/60 rounded" />
              <div className="h-2.5 w-20 bg-[#F3EFE3] rounded" />
            </div>
          ))}
        </div>

        <div className="bg-white rounded-2xl border border-[#DDE9DF] p-5 space-y-4">
          <div className="h-5 w-48 bg-[#F3EFE3] rounded" />
          <div className="space-y-2.5">
            {Array.from({ length: 5 }).map((_, idx) => (
              <div key={idx} className="h-12 bg-[#FAF8F2] rounded-xl border border-[#DDE9DF]/60" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  // 3. Error / Unauthorized / Offline States (No Demo Fallback)
  if (errorInfo && !summary) {
    const ErrorIcon =
      errorInfo.kind === 'offline'
        ? WifiOff
        : errorInfo.kind === 'unauthorized' || errorInfo.kind === 'forbidden'
        ? ShieldAlert
        : AlertCircle;

    return (
      <div
        role="alert"
        className="bg-white rounded-2xl border border-[#EF806D]/40 p-6 sm:p-8 text-center max-w-xl mx-auto my-4 shadow-xs space-y-3"
      >
        <div className="w-12 h-12 mx-auto rounded-xl bg-[#FDF1EF] text-[#B93838] flex items-center justify-center">
          <ErrorIcon className="w-6 h-6" />
        </div>
        <h3 className="text-base font-extrabold text-[#153D32]">
          {errorInfo.title}
        </h3>
        <p className="text-xs sm:text-sm text-[#5E6C64] leading-relaxed">
          {errorInfo.message}
        </p>
        {errorInfo.retryable && (
          <div className="pt-2">
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#153D32] text-[#FAF8F2] text-xs font-bold hover:bg-[#0A241D] transition-colors cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Retry Loading Forecasts</span>
            </button>
          </div>
        )}
      </div>
    );
  }

  const allColdStart =
    summary &&
    summary.total_products_analyzed > 0 &&
    summary.tier_1_count === 0 &&
    summary.tier_2_count === 0 &&
    summary.tier_3_count === summary.total_products_analyzed;

  const renderSortButton = (field: ForecastSortField, label: string, alignRight = false) => {
    const isSorted = sortField === field;
    return (
      <button
        type="button"
        onClick={() => onSortChange(field)}
        aria-label={`Sort by ${label}`}
        className={`inline-flex items-center gap-1 font-extrabold uppercase tracking-wider hover:text-[#153D32] transition-colors cursor-pointer ${
          alignRight ? 'justify-end w-full' : ''
        } ${isSorted ? 'text-[#153D32]' : 'text-[#5E6C64]'}`}
      >
        <span>{label}</span>
        <ArrowUpDown
          className={`w-3 h-3 shrink-0 ${
            isSorted ? 'text-[#23866A]' : 'text-[#5E6C64]/60'
          }`}
        />
        {isSorted && (
          <span className="sr-only">
            ({sortDirection === 'asc' ? 'ascending' : 'descending'})
          </span>
        )}
      </button>
    );
  };

  return (
    <div className="w-full min-w-0 space-y-6">
      {/* Inline non-blocking error banner if refresh failed while existing data is displayed */}
      {errorInfo && summary && (
        <div
          role="alert"
          className="p-3.5 rounded-xl bg-[#FDF1EF] border border-[#EF806D]/40 text-[#B93838] text-xs flex flex-wrap items-center justify-between gap-3"
        >
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>
              <strong>{errorInfo.title}:</strong> {errorInfo.message}
            </span>
          </div>
          {errorInfo.retryable && (
            <button
              type="button"
              onClick={onRetry}
              className="px-3 py-1 rounded-lg bg-white border border-[#EF806D]/40 font-bold text-[#B93838] hover:bg-[#FDF1EF] cursor-pointer"
            >
              Retry
            </button>
          )}
        </div>
      )}

      {/* A. 6 Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-white p-3.5 rounded-2xl border border-[#DDE9DF] shadow-xs">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
            Products Analyzed
          </p>
          <p className="text-xl font-extrabold text-[#153D32] mt-1 tabular-nums">
            {summary?.total_products_analyzed ?? 0}
          </p>
          <p className="text-[10px] text-[#5E6C64] mt-0.5">Active catalog SKUs</p>
        </div>

        <div className="bg-white p-3.5 rounded-2xl border border-[#DDE9DF] shadow-xs">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#23866A]">
            Sufficient History
          </p>
          <p className="text-xl font-extrabold text-[#23866A] mt-1 tabular-nums">
            {summary?.tier_1_count ?? 0}
          </p>
          <p className="text-[10px] text-[#5E6C64] mt-0.5">Tier 1 EWMA model</p>
        </div>

        <div className="bg-white p-3.5 rounded-2xl border border-[#D6AE62]/40 bg-[#FEF9EB]/30 shadow-xs">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#A07828]">
            Sparse History
          </p>
          <p className="text-xl font-extrabold text-[#A07828] mt-1 tabular-nums">
            {summary?.tier_2_count ?? 0}
          </p>
          <p className="text-[10px] text-[#A07828] mt-0.5">Tier 2 linear run-rate</p>
        </div>

        <div className="bg-white p-3.5 rounded-2xl border border-[#DDE9DF] shadow-xs">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
            No Sales History
          </p>
          <p className="text-xl font-extrabold text-[#153D32] mt-1 tabular-nums">
            {summary?.tier_3_count ?? 0}
          </p>
          <p className="text-[10px] text-[#5E6C64] mt-0.5">Tier 3 cold-start</p>
        </div>

        <div className="bg-white p-3.5 rounded-2xl border border-[#D6AE62]/50 bg-[#FEF9EB]/40 shadow-xs">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#A07828]">
            At Risk (≤ 7 Days)
          </p>
          <p className="text-xl font-extrabold text-[#A07828] mt-1 tabular-nums">
            {summary?.at_risk_stockout_7d_count ?? 0}
          </p>
          <p className="text-[10px] text-[#A07828] mt-0.5">Projected stockout risk</p>
        </div>

        <div className="bg-white p-3.5 rounded-2xl border border-[#EF806D]/40 bg-[#FDF1EF]/40 shadow-xs">
          <p className="text-[11px] font-bold uppercase tracking-wider text-[#B93838]">
            Out of Stock
          </p>
          <p className="text-xl font-extrabold text-[#B93838] mt-1 tabular-nums">
            {summary?.out_of_stock_count ?? 0}
          </p>
          <p className="text-[10px] text-[#B93838] mt-0.5">Immediate attention</p>
        </div>
      </div>

      {/* Advisory Notice + Cold-Start Disclosure */}
      <div className="bg-[#FAF8F2] border border-[#DDE9DF] rounded-2xl p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
        <div className="flex items-start gap-2.5 text-[#252D29]">
          <Info className="w-4 h-4 text-[#23866A] shrink-0 mt-0.5" />
          <p className="leading-relaxed">
            <strong>Advisory Forecasts Only:</strong> Demand rates, stockout horizons, and reorder quantities are computed from your store&apos;s recorded transactions. They never automatically modify stock or create supplier orders.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0 max-w-full">
          <label
            htmlFor="forecast-lead-time"
            className="text-[11px] font-bold text-[#5E6C64] whitespace-nowrap"
          >
            Lead-Time Assumption:
          </label>
          <select
            id="forecast-lead-time"
            value={leadTimeDays}
            onChange={(e) => onLeadTimeChange(Number(e.target.value))}
            className="px-2.5 py-1.5 rounded-lg bg-white border border-[#DDE9DF] text-xs font-bold text-[#153D32] cursor-pointer max-w-full"
          >
            <option value={1}>1 day</option>
            <option value={3}>3 days (Default)</option>
            <option value={5}>5 days</option>
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
          </select>
        </div>
      </div>

      {allColdStart && (
        <div className="p-4 rounded-2xl bg-[#FEF9EB]/60 border border-[#D6AE62]/40 flex items-start gap-3 text-xs text-[#252D29]">
          <Sparkles className="w-4 h-4 text-[#A07828] shrink-0 mt-0.5" />
          <div>
            <p className="font-extrabold text-[#153D32]">
              No Recorded Sales History Yet
            </p>
            <p className="text-[#5E6C64] mt-0.5 leading-relaxed">
              All {summary?.total_products_analyzed} active products are currently in Cold Start (Tier 3). ShopPulse does not fabricate category-based demand; forecasts will activate automatically as customer bills are recorded.
            </p>
          </div>
        </div>
      )}

      {/* B. Demand Forecast Table Card */}
      <Card>
        {/* Header & Search/Filters */}
        <div className="space-y-4 pb-4 border-b border-[#DDE9DF]">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="font-extrabold text-[#153D32] text-base flex items-center gap-2">
                <Activity className="w-4 h-4 text-[#23866A]" />
                <span>Product Demand &amp; Stockout Forecast</span>
              </h3>
              <p className="text-xs text-[#5E6C64] mt-0.5">
                Click any product row to inspect model tier, assumptions, warnings, and provisional reorder details.
              </p>
            </div>

            <button
              type="button"
              onClick={onRetry}
              disabled={loading || refreshing}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[#FAF8F2] border border-[#DDE9DF] hover:bg-[#E7F3EE] text-[#153D32] text-xs font-bold transition-colors cursor-pointer disabled:opacity-50 self-start sm:self-auto"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-[#23866A] ${refreshing ? 'animate-spin' : ''}`} />
              <span>{refreshing ? 'Refreshing...' : 'Recompute Live'}</span>
            </button>
          </div>

          {/* Search and Filter Controls */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[#5E6C64] absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Search by product name..."
                aria-label="Search forecast products"
                className="w-full pl-8 pr-3 py-2 text-xs bg-[#FAF8F2] border border-[#DDE9DF] rounded-xl text-[#252D29] placeholder:text-[#5E6C64] focus:outline-none focus:border-[#153D32]"
              />
            </div>

            <div className="relative flex items-center">
              <Filter className="w-3.5 h-3.5 text-[#5E6C64] absolute left-3 pointer-events-none" />
              <select
                aria-label="Filter by forecast tier"
                value={tierFilter}
                onChange={(e) => onTierFilterChange(e.target.value as ForecastTier | 'ALL')}
                className="w-full pl-8 pr-3 py-2 text-xs bg-[#FAF8F2] border border-[#DDE9DF] rounded-xl text-[#153D32] font-semibold cursor-pointer focus:outline-none focus:border-[#153D32]"
              >
                <option value="ALL">All Tiers</option>
                <option value="TIER_1_SUFFICIENT">Tier 1: Sufficient History</option>
                <option value="TIER_2_SPARSE">Tier 2: Sparse History</option>
                <option value="TIER_3_COLD_START">Tier 3: No Sales History</option>
              </select>
            </div>

            <select
              aria-label="Filter by confidence level"
              value={confidenceFilter}
              onChange={(e) => onConfidenceFilterChange(e.target.value as ConfidenceLevel | 'ALL')}
              className="w-full px-3 py-2 text-xs bg-[#FAF8F2] border border-[#DDE9DF] rounded-xl text-[#153D32] font-semibold cursor-pointer focus:outline-none focus:border-[#153D32]"
            >
              <option value="ALL">All Confidence Levels</option>
              <option value="HIGH">HIGH Confidence</option>
              <option value="MEDIUM">MEDIUM Confidence</option>
              <option value="LOW">LOW Confidence</option>
              <option value="NONE">NONE (No History)</option>
            </select>

            <select
              aria-label="Filter by forecast status"
              value={statusFilter}
              onChange={(e) => onStatusFilterChange(e.target.value as ForecastStatus | 'ALL')}
              className="w-full px-3 py-2 text-xs bg-[#FAF8F2] border border-[#DDE9DF] rounded-xl text-[#153D32] font-semibold cursor-pointer focus:outline-none focus:border-[#153D32]"
            >
              <option value="ALL">All Forecast Statuses</option>
              <option value="OUT_OF_STOCK">Out of Stock</option>
              <option value="LOW_STOCK">Low Stock Risk</option>
              <option value="ACTIVE">Active Forecast</option>
              <option value="SPARSE_HISTORY">Sparse History</option>
              <option value="NEW_PRODUCT_NO_SALES_HISTORY">No Sales History</option>
              <option value="UNIT_REVIEW_REQUIRED">Unit Review Required</option>
              <option value="INSUFFICIENT_HISTORY">Insufficient History</option>
            </select>
          </div>
        </div>

        {/* Empty States */}
        {summary && summary.total_products_analyzed === 0 ? (
          <div className="py-12 text-center space-y-2">
            <div className="w-12 h-12 rounded-2xl bg-[#FAF8F2] border border-[#DDE9DF] text-[#5E6C64] flex items-center justify-center mx-auto">
              <Package className="w-6 h-6" />
            </div>
            <h4 className="font-extrabold text-[#153D32] text-sm">
              Empty Product Catalog
            </h4>
            <p className="text-xs text-[#5E6C64] max-w-md mx-auto leading-relaxed">
              Your active catalog has no products yet. Add inventory items or scan a purchase invoice to begin demand forecasting.
            </p>
          </div>
        ) : visibleForecasts.length === 0 ? (
          <div className="py-12 text-center space-y-3">
            <p className="text-xs text-[#5E6C64]">
              No product forecasts match your active search or filter criteria.
            </p>
            {hasActiveFilters && (
              <button
                type="button"
                onClick={onClearFilters}
                className="px-3.5 py-1.5 rounded-xl bg-[#FAF8F2] border border-[#DDE9DF] text-xs font-bold text-[#153D32] hover:bg-[#E7F3EE] cursor-pointer"
              >
                Clear All Filters
              </button>
            )}
          </div>
        ) : (
          <>
            {/* Desktop Responsive Table */}
            <div className="hidden md:block overflow-x-auto mt-3">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#DDE9DF] text-[11px] text-[#5E6C64]">
                    <th
                      className="py-2.5 px-3"
                      aria-sort={sortField === 'product_name' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('product_name', 'Product Name')}
                    </th>
                    <th
                      className="py-2.5 px-3 text-right"
                      aria-sort={sortField === 'current_stock' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('current_stock', 'Stock', true)}
                    </th>
                    <th className="py-2.5 px-2 font-extrabold uppercase tracking-wider">Unit</th>
                    <th
                      className="py-2.5 px-3 text-right"
                      aria-sort={sortField === 'daily_demand_rate' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('daily_demand_rate', 'Daily Demand', true)}
                    </th>
                    <th
                      className="py-2.5 px-3 text-right"
                      aria-sort={sortField === 'expected_seven_day_demand' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('expected_seven_day_demand', '7-Day Demand', true)}
                    </th>
                    <th
                      className="py-2.5 px-3"
                      aria-sort={sortField === 'days_to_stockout' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('days_to_stockout', 'Days to Stockout')}
                    </th>
                    <th
                      className="py-2.5 px-3 text-right"
                      aria-sort={sortField === 'recommended_reorder_quantity' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('recommended_reorder_quantity', 'Reorder Qty', true)}
                    </th>
                    <th
                      className="py-2.5 px-3"
                      aria-sort={sortField === 'confidence_level' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'}
                    >
                      {renderSortButton('confidence_level', 'Confidence')}
                    </th>
                    <th className="py-2.5 px-3 font-extrabold uppercase tracking-wider">
                      Status
                    </th>
                    <th className="py-2.5 px-2 text-right font-extrabold uppercase tracking-wider">
                      Details
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#DDE9DF]">
                  {visibleForecasts.map((item) => {
                    const severity = getStockoutSeverity(item);
                    const confidence = getConfidenceMetadata(item.confidence_level);
                    const tier = getForecastTierMetadata(item.forecast_tier);
                    const statusLabel = getForecastStatusLabel(item.forecast_status);

                    return (
                      <tr
                        key={item.product_id}
                        tabIndex={0}
                        role="button"
                        aria-label={`Inspect demand forecast for ${item.product_name}`}
                        onClick={() => onSelectProduct(item)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSelectProduct(item);
                          }
                        }}
                        className="hover:bg-[#FAF8F2] focus:bg-[#FAF8F2] focus:outline-none transition-colors cursor-pointer"
                      >
                        <td className="py-3 px-3">
                          <p className="font-extrabold text-[#153D32]">{item.product_name}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <span className="text-[10px] font-semibold text-[#5E6C64]">
                              {tier.shortLabel}
                            </span>
                            {item.warnings.length > 0 && (
                              <span
                                title={item.warnings.join(' | ')}
                                className="inline-flex items-center gap-0.5 text-[10px] font-bold text-[#A07828]"
                              >
                                <AlertTriangle className="w-3 h-3" />
                                {item.warnings.length}
                              </span>
                            )}
                          </div>
                        </td>

                        <td className="py-3 px-3 text-right font-extrabold text-[#153D32] tabular-nums">
                          {formatForecastNumber(item.current_stock, 2)}
                        </td>

                        <td className="py-3 px-2 text-[#5E6C64] font-medium">
                          {item.normalized_unit}
                        </td>

                        <td className="py-3 px-3 text-right font-semibold text-[#252D29] tabular-nums">
                          {item.daily_demand_rate !== null
                            ? formatForecastNumber(item.daily_demand_rate, 2)
                            : '—'}
                        </td>

                        <td className="py-3 px-3 text-right font-semibold text-[#252D29] tabular-nums">
                          {item.expected_seven_day_demand !== null
                            ? formatForecastNumber(item.expected_seven_day_demand, 2)
                            : '—'}
                        </td>

                        <td className="py-3 px-3">
                          <div className="flex flex-col items-start gap-1">
                            <span
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wide ${severity.badgeClass}`}
                              title={severity.description}
                            >
                              <span className={`w-1.5 h-1.5 rounded-full ${severity.dotClass}`} />
                              {severity.label}
                            </span>
                            <span className="text-[11px] font-bold text-[#252D29] tabular-nums">
                              {item.days_to_stockout !== null
                                ? `${formatForecastNumber(item.days_to_stockout, 1)} days`
                                : 'Unavailable'}
                            </span>
                          </div>
                        </td>

                        <td className="py-3 px-3 text-right">
                          <div className="flex flex-col items-end">
                            <span className="font-extrabold text-[#153D32] tabular-nums">
                              {item.recommended_reorder_quantity !== null
                                ? `${formatForecastNumber(item.recommended_reorder_quantity, 2)} ${item.normalized_unit}`
                                : '—'}
                            </span>
                            {item.is_reorder_provisional && (
                              <span className="text-[10px] font-bold text-[#A07828]">
                                Provisional
                              </span>
                            )}
                          </div>
                        </td>

                        <td className="py-3 px-3">
                          <div className="flex flex-col items-start gap-0.5">
                            <span
                              className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-extrabold ${confidence.badgeClass}`}
                              title={confidence.explanation}
                            >
                              {confidence.label}
                            </span>
                            <span className="text-[10px] text-[#5E6C64] line-clamp-1 max-w-[130px]">
                              {confidence.explanation}
                            </span>
                          </div>
                        </td>

                        <td className="py-3 px-3">
                          <span className="text-[11px] font-semibold text-[#252D29]">
                            {statusLabel}
                          </span>
                        </td>

                        <td className="py-3 px-2 text-right">
                          <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-[#FAF8F2] border border-[#DDE9DF] text-[#153D32]">
                            <ChevronRight className="w-4 h-4" />
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile Card Layout */}
            <div className="md:hidden space-y-3 mt-3">
              {visibleForecasts.map((item) => {
                const severity = getStockoutSeverity(item);
                const confidence = getConfidenceMetadata(item.confidence_level);
                const tier = getForecastTierMetadata(item.forecast_tier);
                const statusLabel = getForecastStatusLabel(item.forecast_status);

                return (
                  <button
                    key={item.product_id}
                    type="button"
                    onClick={() => onSelectProduct(item)}
                    aria-label={`Inspect demand forecast for ${item.product_name}`}
                    className="w-full text-left p-4 rounded-2xl bg-[#FAF8F2] border border-[#DDE9DF] hover:border-[#23866A]/50 transition-all space-y-3 cursor-pointer"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-extrabold text-[#153D32] text-sm truncate">
                          {item.product_name}
                        </p>
                        <p className="text-[11px] text-[#5E6C64] mt-0.5">
                          {tier.shortLabel} • {statusLabel}
                        </p>
                      </div>
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wide shrink-0 ${severity.badgeClass}`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full ${severity.dotClass}`} />
                        {severity.label}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs bg-white p-3 rounded-xl border border-[#DDE9DF]/80">
                      <div>
                        <span className="text-[10px] uppercase text-[#5E6C64] font-bold block">
                          Current Stock
                        </span>
                        <span className="font-extrabold text-[#153D32] tabular-nums">
                          {formatForecastNumber(item.current_stock, 2)} {item.normalized_unit}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-[#5E6C64] font-bold block">
                          Days to Stockout
                        </span>
                        <span className="font-extrabold text-[#153D32] tabular-nums">
                          {item.days_to_stockout !== null
                            ? `${formatForecastNumber(item.days_to_stockout, 1)} days`
                            : 'Unavailable'}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-[#5E6C64] font-bold block">
                          Daily / 7-Day Demand
                        </span>
                        <span className="font-bold text-[#252D29] tabular-nums">
                          {item.daily_demand_rate !== null
                            ? `${formatForecastNumber(item.daily_demand_rate, 2)} / ${formatForecastNumber(item.expected_seven_day_demand, 2)} ${item.normalized_unit}`
                            : '—'}
                        </span>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-[#5E6C64] font-bold block">
                          Reorder Qty
                        </span>
                        <span className="font-extrabold text-[#153D32] tabular-nums">
                          {item.recommended_reorder_quantity !== null
                            ? `${formatForecastNumber(item.recommended_reorder_quantity, 2)} ${item.normalized_unit}`
                            : '—'}
                        </span>
                        {item.is_reorder_provisional && (
                          <span className="block text-[10px] font-bold text-[#A07828]">
                            Provisional
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between gap-2 pt-0.5">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-extrabold ${confidence.badgeClass}`}
                      >
                        Confidence: {confidence.label}
                      </span>
                      <span className="inline-flex items-center gap-1 text-xs font-bold text-[#153D32]">
                        <span>Inspect Details</span>
                        <ChevronRight className="w-4 h-4 text-[#23866A]" />
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </>
        )}
      </Card>

      {/* Product Forecast Detail Modal */}
      <ProductForecastDetailModal
        forecast={selectedProduct}
        leadTimeDays={leadTimeDays}
        onClose={() => onSelectProduct(null)}
      />
    </div>
  );
};

export interface DemandForecastSectionProps {
  refreshSignal?: number;
  onSummaryLoaded?: (summary: ShopForecastSummary | null) => void;
}

export const DemandForecastSection: React.FC<DemandForecastSectionProps> = ({
  refreshSignal = 0,
  onSummaryLoaded,
}) => {
  const { role, isCashier, canAccessAnalytics } = useShopRole();
  const isRestricted = isCashier || !canAccessAnalytics;

  const [summary, setSummary] = useState<ShopForecastSummary | null>(null);
  const [loading, setLoading] = useState<boolean>(!isRestricted);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [errorInfo, setErrorInfo] = useState<ForecastErrorInfo | null>(null);

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [tierFilter, setTierFilter] = useState<ForecastTier | 'ALL'>('ALL');
  const [statusFilter, setStatusFilter] = useState<ForecastStatus | 'ALL'>('ALL');
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceLevel | 'ALL'>('ALL');
  const [leadTimeDays, setLeadTimeDays] = useState<number>(3);
  const [sortField, setSortField] = useState<ForecastSortField>('days_to_stockout');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [selectedProduct, setSelectedProduct] = useState<ProductDemandForecast | null>(null);

  const fetchForecast = useCallback(
    async (bypassCache = false) => {
      if (isRestricted) {
        setLoading(false);
        return;
      }

      if (bypassCache) setRefreshing(true);
      else setLoading(true);
      setErrorInfo(null);

      try {
        const res = await insightsApi.getDemandForecast({
          forecast_tier: tierFilter !== 'ALL' ? tierFilter : undefined,
          forecast_status: statusFilter !== 'ALL' ? statusFilter : undefined,
          confidence_level: confidenceFilter !== 'ALL' ? confidenceFilter : undefined,
          lead_time_days: leadTimeDays,
          no_cache: bypassCache,
        });
        setSummary(res);
        onSummaryLoaded?.(res);
      } catch (err) {
        const classified = classifyForecastApiError(err);
        setErrorInfo(classified);
        if (classified.kind === 'unauthorized' || classified.kind === 'forbidden') {
          setSummary(null);
          onSummaryLoaded?.(null);
        }
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [
      isRestricted,
      tierFilter,
      statusFilter,
      confidenceFilter,
      leadTimeDays,
      onSummaryLoaded,
    ]
  );

  useEffect(() => {
    fetchForecast(refreshSignal > 0);
  }, [fetchForecast, refreshSignal]);

  const handleSortChange = (field: ForecastSortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const handleClearFilters = () => {
    setSearchQuery('');
    setTierFilter('ALL');
    setStatusFilter('ALL');
    setConfidenceFilter('ALL');
  };

  return (
    <DemandForecastView
      summary={summary}
      loading={loading}
      refreshing={refreshing}
      errorInfo={errorInfo}
      searchQuery={searchQuery}
      tierFilter={tierFilter}
      statusFilter={statusFilter}
      confidenceFilter={confidenceFilter}
      leadTimeDays={leadTimeDays}
      sortField={sortField}
      sortDirection={sortDirection}
      selectedProduct={selectedProduct}
      isRestricted={isRestricted}
      userRole={role}
      onSearchChange={setSearchQuery}
      onTierFilterChange={setTierFilter}
      onStatusFilterChange={setStatusFilter}
      onConfidenceFilterChange={setConfidenceFilter}
      onLeadTimeChange={setLeadTimeDays}
      onSortChange={handleSortChange}
      onSelectProduct={setSelectedProduct}
      onClearFilters={handleClearFilters}
      onRetry={() => fetchForecast(true)}
    />
  );
};
