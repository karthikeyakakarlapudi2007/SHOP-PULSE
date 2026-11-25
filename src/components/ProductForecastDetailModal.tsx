import React, { useEffect } from 'react';
import {
  X,
  AlertTriangle,
  Info,
  Package,
  Calendar,
  TrendingUp,
  Clock,
  ShieldCheck,
  AlertCircle,
} from 'lucide-react';
import type { ProductDemandForecast } from '../api/insights';
import {
  formatForecastNumber,
  getConfidenceMetadata,
  getForecastStatusLabel,
  getForecastTierMetadata,
  getStockoutSeverity,
} from '../utils/demandForecast';

export interface ProductForecastDetailModalProps {
  forecast: ProductDemandForecast | null;
  leadTimeDays?: number;
  onClose: () => void;
}

export const ProductForecastDetailModal: React.FC<ProductForecastDetailModalProps> = ({
  forecast,
  leadTimeDays = 3,
  onClose,
}) => {
  useEffect(() => {
    if (!forecast) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [forecast, onClose]);

  if (!forecast) return null;

  const severity = getStockoutSeverity(forecast);
  const confidence = getConfidenceMetadata(forecast.confidence_level);
  const tier = getForecastTierMetadata(forecast.forecast_tier);
  const statusLabel = getForecastStatusLabel(forecast.forecast_status);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-[#0A241D]/45 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="forecast-detail-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto bg-[#FAF8F2] rounded-2xl border border-[#DDE9DF] shadow-xl text-[#252D29]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 bg-white border-b border-[#DDE9DF] px-5 py-4 flex items-start justify-between gap-4 rounded-t-2xl">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span
                className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-extrabold uppercase tracking-wide ${severity.badgeClass}`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${severity.dotClass}`} />
                {severity.label}
              </span>
              <span
                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold ${tier.badgeClass}`}
              >
                {tier.shortLabel}
              </span>
            </div>
            <h2
              id="forecast-detail-title"
              className="text-lg font-extrabold text-[#153D32] truncate"
            >
              {forecast.product_name}
            </h2>
            <p className="text-xs text-[#5E6C64]">
              Status: <span className="font-semibold text-[#153D32]">{statusLabel}</span> • Normalized Unit:{' '}
              <span className="font-semibold text-[#153D32]">{forecast.normalized_unit}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close forecast details"
            className="p-2 rounded-xl text-[#5E6C64] hover:text-[#153D32] hover:bg-[#FAF8F2] transition-colors cursor-pointer shrink-0"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-5">
          {/* Primary Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div className="bg-white p-3.5 rounded-xl border border-[#DDE9DF]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
                <Package className="w-3.5 h-3.5 text-[#23866A]" />
                <span>Current Stock</span>
              </div>
              <p className="text-lg font-extrabold text-[#153D32] mt-1 tabular-nums">
                {formatForecastNumber(forecast.current_stock, 2)} {forecast.normalized_unit}
              </p>
            </div>

            <div className="bg-white p-3.5 rounded-xl border border-[#DDE9DF]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
                <TrendingUp className="w-3.5 h-3.5 text-[#23866A]" />
                <span>Daily Demand Rate</span>
              </div>
              <p className="text-lg font-extrabold text-[#153D32] mt-1 tabular-nums">
                {forecast.daily_demand_rate !== null
                  ? `${formatForecastNumber(forecast.daily_demand_rate, 2)} ${forecast.normalized_unit}/day`
                  : 'Unavailable'}
              </p>
            </div>

            <div className="bg-white p-3.5 rounded-xl border border-[#DDE9DF]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
                <Calendar className="w-3.5 h-3.5 text-[#23866A]" />
                <span>7-Day Expected</span>
              </div>
              <p className="text-lg font-extrabold text-[#153D32] mt-1 tabular-nums">
                {forecast.expected_seven_day_demand !== null
                  ? `${formatForecastNumber(forecast.expected_seven_day_demand, 2)} ${forecast.normalized_unit}`
                  : 'Unavailable'}
              </p>
            </div>

            <div className="bg-white p-3.5 rounded-xl border border-[#DDE9DF]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
                <Clock className="w-3.5 h-3.5 text-[#D6AE62]" />
                <span>Days to Stockout</span>
              </div>
              <p className="text-lg font-extrabold text-[#153D32] mt-1 tabular-nums">
                {forecast.days_to_stockout !== null
                  ? `${formatForecastNumber(forecast.days_to_stockout, 1)} days`
                  : 'Unavailable'}
              </p>
              <p className="text-[11px] text-[#5E6C64] mt-0.5">{severity.description}</p>
            </div>

            <div className="bg-white p-3.5 rounded-xl border border-[#DDE9DF]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
                <ShieldCheck className="w-3.5 h-3.5 text-[#23866A]" />
                <span>Valid Sales Events</span>
              </div>
              <p className="text-lg font-extrabold text-[#153D32] mt-1 tabular-nums">
                {forecast.total_valid_sales}
              </p>
              <p className="text-[11px] text-[#5E6C64] mt-0.5">
                Over {forecast.observable_days} observable days
              </p>
            </div>

            <div className="bg-white p-3.5 rounded-xl border border-[#DDE9DF]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-[#5E6C64]">
                <Info className="w-3.5 h-3.5 text-[#3567A8]" />
                <span>Confidence Level</span>
              </div>
              <div className="mt-1">
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-extrabold ${confidence.badgeClass}`}
                >
                  {confidence.label}
                </span>
              </div>
              <p className="text-[11px] text-[#5E6C64] mt-1 leading-snug">
                {confidence.explanation}
              </p>
            </div>
          </div>

          {/* Advisory Reorder Recommendation Card */}
          <div className="bg-white p-4 rounded-xl border border-[#DDE9DF] space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-xs font-extrabold uppercase tracking-wider text-[#153D32]">
                Reorder Recommendation (Advisory Only)
              </h3>
              {forecast.is_reorder_provisional && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-[#FEF9EB] text-[#A07828] border border-[#D6AE62]/40">
                  <AlertCircle className="w-3 h-3" />
                  Provisional Estimate
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs pt-1">
              <div>
                <span className="text-[#5E6C64] block">Current Stock</span>
                <span className="font-bold text-[#153D32] tabular-nums">
                  {formatForecastNumber(forecast.current_stock, 2)} {forecast.normalized_unit}
                </span>
              </div>
              <div>
                <span className="text-[#5E6C64] block">Recommended Reorder Qty</span>
                <span className="font-extrabold text-[#153D32] text-sm tabular-nums">
                  {forecast.recommended_reorder_quantity !== null
                    ? `${formatForecastNumber(forecast.recommended_reorder_quantity, 2)} ${forecast.normalized_unit}`
                    : 'Unavailable (No Sales History)'}
                </span>
              </div>
              <div>
                <span className="text-[#5E6C64] block">Lead-Time Assumption</span>
                <span className="font-bold text-[#153D32]">
                  {leadTimeDays} {leadTimeDays === 1 ? 'day' : 'days'}
                </span>
              </div>
            </div>

            {forecast.is_reorder_provisional && (
              <p className="text-[11px] text-[#A07828] bg-[#FEF9EB]/70 border border-[#D6AE62]/30 rounded-lg px-3 py-2 leading-relaxed">
                <strong>Provisional safety-stock disclosure:</strong> Explicit safety stock is not configured; the product&apos;s{' '}
                <code className="font-mono">reorder_level</code> threshold is used provisionally when calculating this recommendation.
              </p>
            )}

            <p className="text-[11px] text-[#5E6C64] leading-relaxed">
              This is an advisory estimate only. Reviewing this recommendation does not modify inventory or place supplier orders automatically.
            </p>
          </div>

          {/* Warnings (Never hidden) */}
          {forecast.warnings.length > 0 && (
            <div className="bg-[#FDF1EF] border border-[#EF806D]/40 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs font-extrabold text-[#B93838] uppercase tracking-wider">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>Warnings &amp; Uncertainty Notices</span>
              </div>
              <ul className="space-y-1.5 text-xs text-[#252D29]">
                {forecast.warnings.map((warning, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#B93838] mt-1.5 shrink-0" />
                    <span>{warning}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Forecast Assumptions */}
          <div className="bg-white border border-[#DDE9DF] rounded-xl p-4 space-y-2">
            <div className="flex items-center gap-2 text-xs font-extrabold text-[#153D32] uppercase tracking-wider">
              <Info className="w-4 h-4 text-[#23866A] shrink-0" />
              <span>Model Tier &amp; Forecast Assumptions</span>
            </div>
            <p className="text-xs text-[#5E6C64]">
              <strong className="text-[#153D32]">{tier.label}:</strong> {tier.description}
            </p>
            {forecast.assumptions.length > 0 ? (
              <ul className="space-y-1.5 text-xs text-[#252D29] pt-1">
                {forecast.assumptions.map((assumption, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#23866A] mt-1.5 shrink-0" />
                    <span>{assumption}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-[#5E6C64]">No additional assumptions recorded.</p>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="bg-white border-t border-[#DDE9DF] px-5 py-3 flex justify-end rounded-b-2xl">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-[#153D32] text-[#FAF8F2] text-xs font-bold hover:bg-[#0A241D] transition-colors cursor-pointer"
          >
            Close Details
          </button>
        </div>
      </div>
    </div>
  );
};
