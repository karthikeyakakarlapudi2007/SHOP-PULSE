import React, { useState } from 'react';
import { TrendingUp, ArrowUpRight, Calendar, Info } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageContext';
import type { PageRoute } from '../../types';

export interface DailyPoint {
  day: string;
  date?: string;
  amount: number;
  height?: string;
  itemsCount?: number;
  isToday?: boolean;
}

interface SalesOverviewProps {
  totalRevenue?: number;
  /** Backwards compatibility prop */
  totalWeekRevenue?: number;
  growthPercent?: string;
  /** Backwards compatibility prop */
  weekGrowthPercent?: string;
  averageDailyRevenue?: number;
  data?: DailyPoint[];
  period?: '7days' | '30days';
  onPeriodChange?: (period: '7days' | '30days') => void;
  setActivePage?: (page: PageRoute) => void;
  isLoading?: boolean;
}

function formatCompactRupee(val: number): string {
  if (val >= 10000000) return `₹${(val / 10000000).toFixed(1)}Cr`;
  if (val >= 100000) return `₹${(val / 100000).toFixed(1)}L`;
  if (val >= 1000) return `₹${(val / 1000).toFixed(val >= 10000 ? 0 : 1)}k`;
  return `₹${Math.round(val)}`;
}

export const SalesOverview: React.FC<SalesOverviewProps> = ({
  totalRevenue,
  totalWeekRevenue,
  growthPercent,
  weekGrowthPercent,
  averageDailyRevenue,
  data = [],
  period = '7days',
  onPeriodChange,
  setActivePage,
  isLoading = false,
}) => {
  const { t } = useLanguage();
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  const displayRevenue = totalRevenue ?? totalWeekRevenue ?? 0;
  const displayGrowth = growthPercent ?? weekGrowthPercent;
  const points = data;
  const hasData = points.some((p) => p.amount > 0);

  // SVG Chart Geometry
  const svgWidth = 540;
  const svgHeight = 190;
  const padLeft = 52;
  const padRight = 20;
  const padTop = 20;
  const padBottom = 32;

  const plotWidth = svgWidth - padLeft - padRight;
  const plotHeight = svgHeight - padTop - padBottom;

  const maxVal = Math.max(...points.map((p) => p.amount), 0);
  const chartMax = maxVal > 0 ? Math.ceil(maxVal * 1.18) : 1000;

  // Horizontal Gridline Steps
  const gridSteps = [1, 0.66, 0.33, 0];
  const gridLines = gridSteps.map((step) => ({
    y: padTop + plotHeight * (1 - step),
    val: Math.round(chartMax * step),
    isBottom: step === 0,
  }));

  // Coordinate Calculations
  const calculatedPoints = points.map((p, idx) => {
    const total = points.length;
    const x = total > 1 ? padLeft + (idx / (total - 1)) * plotWidth : padLeft + plotWidth / 2;
    const y = padTop + plotHeight - (p.amount / chartMax) * plotHeight;
    return { ...p, x, y, idx };
  });

  // Smooth Bezier Curve Path
  let pathD = '';
  let areaD = '';

  if (calculatedPoints.length > 0) {
    pathD = `M ${calculatedPoints[0].x} ${calculatedPoints[0].y}`;
    for (let i = 0; i < calculatedPoints.length - 1; i++) {
      const p0 = calculatedPoints[i];
      const p1 = calculatedPoints[i + 1];
      const cp1x = p0.x + (p1.x - p0.x) / 2;
      const cp1y = p0.y;
      const cp2x = p0.x + (p1.x - p0.x) / 2;
      const cp2y = p1.y;
      pathD += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p1.x} ${p1.y}`;
    }

    const baselineY = padTop + plotHeight;
    const firstX = calculatedPoints[0].x;
    const lastX = calculatedPoints[calculatedPoints.length - 1].x;
    areaD = `${pathD} L ${lastX} ${baselineY} L ${firstX} ${baselineY} Z`;
  }

  const activePoint = hoveredIdx !== null && calculatedPoints[hoveredIdx] ? calculatedPoints[hoveredIdx] : null;

  return (
    <div className="bg-white rounded-2xl border border-[#DDE9DF] p-5 sm:p-6 shadow-card flex flex-col justify-between h-full transition-all">
      <div>
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#DDE9DF]">
          <div>
            <h2 className="font-extrabold text-[#252D29] text-base flex items-center gap-2">
              <span className="w-7 h-7 rounded-lg bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0 border border-[#23866A]/20">
                <TrendingUp className="w-4 h-4" />
              </span>
              <span>{t('dashboard.salesOverview')}</span>
            </h2>
            <p className="text-xs text-[#5E6C64] font-medium mt-0.5">
              {period === '30days' ? 'Daily revenue trend past 30 days' : t('dashboard.dailyRevenue7Days')}
            </p>
          </div>

          <div className="flex items-center gap-2.5 shrink-0 self-start sm:self-center">
            {onPeriodChange && (
              <div className="inline-flex items-center bg-[#FAF8F2] p-0.5 rounded-lg border border-[#DDE9DF] text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => onPeriodChange('7days')}
                  className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                    period === '7days'
                      ? 'bg-[#153D32] text-white shadow-card'
                      : 'text-[#5E6C64] hover:text-[#252D29]'
                  }`}
                >
                  7D
                </button>
                <button
                  type="button"
                  onClick={() => onPeriodChange('30days')}
                  className={`px-2.5 py-1 rounded-md transition-colors cursor-pointer ${
                    period === '30days'
                      ? 'bg-[#153D32] text-white shadow-card'
                      : 'text-[#5E6C64] hover:text-[#252D29]'
                  }`}
                >
                  30D
                </button>
              </div>
            )}

            {setActivePage && (
              <button
                onClick={() => setActivePage('insights')}
                className="text-xs font-bold text-[#153D32] hover:underline flex items-center gap-0.5 cursor-pointer ml-1"
              >
                <span>{t('dashboard.viewAll')}</span>
                <ArrowUpRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Revenue KPI Summary Strip */}
        <div className="mt-3.5 bg-[#FAF8F2] rounded-2xl p-3.5 border border-[#DDE9DF] flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-wider text-[#5E6C64]">
              {period === '30days' ? 'Past 30 Days Revenue' : t('dashboard.thisWeek')}
            </p>
            <div className="text-xl sm:text-2xl font-extrabold text-[#252D29] mt-0.5 tracking-tight truncate">
              ₹{displayRevenue.toLocaleString('en-IN')}
            </div>
            {typeof averageDailyRevenue === 'number' && averageDailyRevenue > 0 && (
              <p className="text-[11px] text-[#5E6C64] font-medium mt-0.5">
                Avg. ₹{averageDailyRevenue.toLocaleString('en-IN')}/day
              </p>
            )}
          </div>

          {displayGrowth && (
            <div className="text-right shrink-0">
              <span className="inline-flex items-center gap-1 text-xs font-bold text-[#23866A] bg-[#E7F3EE] px-2.5 py-1 rounded-full border border-[#23866A]/30">
                <span>{displayGrowth}</span>
                <span className="hidden xs:inline">{t('dashboard.vsLastWeek')}</span>
              </span>
            </div>
          )}
        </div>

        {/* Line Chart Area */}
        {isLoading ? (
          <div className="h-44 flex flex-col items-center justify-center gap-2 text-xs font-medium text-[#5E6C64] animate-pulse">
            <div className="w-full h-28 bg-[#FAF8F2] rounded-lg"></div>
            <span>Loading telemetry...</span>
          </div>
        ) : !hasData ? (
          <div className="h-44 flex flex-col items-center justify-center text-center p-4 bg-[#FAF8F2]/60 rounded-lg border border-dashed border-[#DDE9DF] my-2">
            <Calendar className="w-6 h-6 text-[#23866A] mb-1.5 opacity-80" />
            <p className="text-xs font-bold text-[#252D29]">No Sales Recorded For This Period</p>
            <p className="text-[11px] text-[#5E6C64] max-w-xs mt-0.5">
              Once customer sales are completed, verified daily revenue trends will appear here.
            </p>
          </div>
        ) : (
          <div className="relative w-full pt-2">
            <svg
              viewBox={`0 0 ${svgWidth} ${svgHeight}`}
              className="w-full h-44 select-none overflow-visible"
              role="img"
              aria-label="Sales performance line chart"
              onMouseLeave={() => setHoveredIdx(null)}
            >
              <defs>
                <linearGradient id="salesOverviewGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                  <stop offset="0%" stopColor="#153D32" stopOpacity="0.18" />
                  <stop offset="100%" stopColor="#153D32" stopOpacity="0.01" />
                </linearGradient>
              </defs>

              {/* Gridlines */}
              {gridLines.map((line, idx) => (
                <g key={idx}>
                  <line
                    x1={padLeft}
                    y1={line.y}
                    x2={svgWidth - padRight}
                    y2={line.y}
                    stroke="#DDE9DF"
                    strokeWidth="1"
                    strokeDasharray={line.isBottom ? undefined : '3 3'}
                  />
                  <text
                    x={padLeft - 8}
                    y={line.y + 3.5}
                    textAnchor="end"
                    fontSize="9.5"
                    fontFamily="Inter, sans-serif"
                    fill="#5E6C64"
                    fontWeight="600"
                  >
                    {formatCompactRupee(line.val)}
                  </text>
                </g>
              ))}

              {/* Gradient Area Fill */}
              <path d={areaD} fill="url(#salesOverviewGrad)" />

              {/* Solid Green Line */}
              <path
                d={pathD}
                fill="none"
                stroke="#153D32"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Active Guide Crosshair */}
              {activePoint && (
                <line
                  x1={activePoint.x}
                  y1={padTop}
                  x2={activePoint.x}
                  y2={padTop + plotHeight}
                  stroke="#23866A"
                  strokeWidth="1"
                  strokeDasharray="2 2"
                />
              )}

              {/* Data Points & X-Labels */}
              {calculatedPoints.map((p, idx) => {
                const isHovered = hoveredIdx === idx;
                const showXLabel = calculatedPoints.length <= 8 || idx % Math.ceil(calculatedPoints.length / 6) === 0 || idx === calculatedPoints.length - 1;

                return (
                  <g key={idx} className="cursor-pointer">
                    <rect
                      x={p.x - 16}
                      y={padTop}
                      width={32}
                      height={plotHeight + padBottom}
                      fill="transparent"
                      onMouseEnter={() => setHoveredIdx(idx)}
                      onClick={() => setHoveredIdx(idx)}
                    />

                    <circle
                      cx={p.x}
                      cy={p.y}
                      r={isHovered ? 5.5 : p.isToday ? 4 : 3}
                      fill="#FFFFFF"
                      stroke={p.isToday ? '#23866A' : '#153D32'}
                      strokeWidth={isHovered ? 2.5 : p.isToday ? 2.5 : 2}
                      className="transition-all duration-150"
                    />

                    {showXLabel && (
                      <text
                        x={p.x}
                        y={svgHeight - 10}
                        textAnchor="middle"
                        fontSize="9.5"
                        fontFamily="Inter, sans-serif"
                        fontWeight={p.isToday || isHovered ? '700' : '500'}
                        fill={p.isToday ? '#153D32' : isHovered ? '#252D29' : '#5E6C64'}
                      >
                        {p.day.replace(' (Today)', '')}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>

            {/* Hover Tooltip */}
            {activePoint && (
              <div
                className="absolute pointer-events-none transform -translate-x-1/2 bg-[#252D29] text-white rounded-lg px-2.5 py-1.5 text-xs shadow-md z-20 transition-all border border-[#23866A]/40"
                style={{
                  left: `${(activePoint.x / svgWidth) * 100}%`,
                  top: `${Math.max(2, (activePoint.y / svgHeight) * 100 - 32)}%`,
                }}
              >
                <div className="font-bold text-slate-100 flex items-center justify-between gap-2">
                  <span>{activePoint.day}</span>
                  {activePoint.date && (
                    <span className="text-[10px] text-slate-300 font-normal">{activePoint.date}</span>
                  )}
                </div>
                <div className="mt-0.5 font-extrabold text-[#E7F3EE]">
                  ₹{activePoint.amount.toLocaleString('en-IN')}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="pt-2.5 border-t border-[#DDE9DF] mt-1 flex items-center justify-between text-[11px] text-[#5E6C64]">
        <div className="flex items-center gap-1.5">
          <Info className="w-3 h-3 text-[#23866A]" />
          <span>Verified sales stream</span>
        </div>
        <div className="flex items-center gap-1.5 font-medium">
          <span className="w-2 h-2 rounded-full bg-[#153D32]"></span>
          <span>Revenue (₹)</span>
        </div>
      </div>
    </div>
  );
};
