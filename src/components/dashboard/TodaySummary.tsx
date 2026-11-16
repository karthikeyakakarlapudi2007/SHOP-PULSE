import React from 'react';
import { IndianRupee, ShoppingBag, Package, TrendingUp, Receipt, ArrowUpRight } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageContext';
import type { PageRoute } from '../../types';

interface TodaySummaryProps {
  revenue: number;
  itemsSold: number;
  productsCount: number;
  billsCount?: number;
  growthPercent?: string;
  setActivePage: (page: PageRoute) => void;
}

export const TodaySummary: React.FC<TodaySummaryProps> = ({
  revenue,
  itemsSold,
  productsCount,
  billsCount = 0,
  growthPercent,
  setActivePage,
}) => {
  const { t } = useLanguage();

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 lg:gap-5">
      
      {/* Metric 1: Today's Revenue */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] p-4 sm:p-5 shadow-card transition-all hover:border-[#23866A]/40 hover:shadow-card-hover flex flex-col justify-between min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-[#5E6C64] truncate" title={t('dashboard.todaysSales')}>
            {t('dashboard.todaysSales')}
          </span>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0 border border-[#23866A]/20">
            <IndianRupee className="w-4 h-4 sm:w-5 sm:h-5 text-[#23866A]" />
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3">
          <div className="text-2xl sm:text-3xl font-black text-[#153D32] tracking-tight truncate">
            ₹{revenue.toLocaleString('en-IN')}
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3 pt-2.5 sm:pt-3 border-t border-[#DDE9DF] flex items-center justify-between gap-2 text-xs">
          {growthPercent ? (
            <span className="inline-flex items-center gap-1 font-bold text-[#23866A] truncate">
              <TrendingUp className="w-3.5 h-3.5 shrink-0" />
              <span>{growthPercent}</span>
            </span>
          ) : (
            <span className="text-[#5E6C64] font-medium truncate">Recorded today</span>
          )}
          <button
            onClick={() => setActivePage('sales')}
            className="text-[#23866A] hover:underline font-bold inline-flex items-center gap-1 cursor-pointer ml-auto shrink-0 min-h-[36px]"
          >
            <span>POS</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Metric 2: Items Sold */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] p-4 sm:p-5 shadow-card transition-all hover:border-[#23866A]/40 hover:shadow-card-hover flex flex-col justify-between min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-[#5E6C64] truncate" title={t('dashboard.itemsSoldToday')}>
            {t('dashboard.itemsSoldToday')}
          </span>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0 border border-[#23866A]/20">
            <ShoppingBag className="w-4 h-4 sm:w-5 sm:h-5 text-[#23866A]" />
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3">
          <div className="text-2xl sm:text-3xl font-black text-[#153D32] tracking-tight truncate">
            {itemsSold.toLocaleString('en-IN')}
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3 pt-2.5 sm:pt-3 border-t border-[#DDE9DF] flex items-center justify-between gap-2 text-xs text-[#5E6C64]">
          <span className="font-medium truncate">Customer items</span>
          <button
            onClick={() => setActivePage('sales')}
            className="text-[#23866A] hover:underline font-bold inline-flex items-center gap-1 cursor-pointer shrink-0 min-h-[36px]"
          >
            <span>History</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Metric 3: Total Transactions / Bills */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] p-4 sm:p-5 shadow-card transition-all hover:border-[#23866A]/40 hover:shadow-card-hover flex flex-col justify-between min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-[#5E6C64] truncate" title="Bills Completed">
            Bills Completed
          </span>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-[#FBF4E7] text-[#D6AE62] flex items-center justify-center shrink-0 border border-[#D6AE62]/30">
            <Receipt className="w-4 h-4 sm:w-5 sm:h-5 text-[#A07828]" />
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3">
          <div className="text-2xl sm:text-3xl font-black text-[#153D32] tracking-tight truncate">
            {billsCount.toLocaleString('en-IN')}
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3 pt-2.5 sm:pt-3 border-t border-[#DDE9DF] flex items-center justify-between gap-2 text-xs text-[#5E6C64]">
          <span className="font-medium truncate">In-store receipts</span>
          <button
            onClick={() => setActivePage('sales')}
            className="text-[#23866A] hover:underline font-bold inline-flex items-center gap-1 cursor-pointer shrink-0 min-h-[36px]"
          >
            <span>Receipts</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Metric 4: Active Stock Catalog */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] p-4 sm:p-5 shadow-card transition-all hover:border-[#23866A]/40 hover:shadow-card-hover flex flex-col justify-between min-w-0">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-[#5E6C64] truncate" title={t('dashboard.productsCount')}>
            {t('dashboard.productsCount')}
          </span>
          <div className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl bg-[#FAF8F2] text-[#153D32] flex items-center justify-center shrink-0 border border-[#DDE9DF]">
            <Package className="w-4 h-4 sm:w-5 sm:h-5 text-[#23866A]" />
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3">
          <div className="text-2xl sm:text-3xl font-black text-[#153D32] tracking-tight truncate">
            {productsCount.toLocaleString('en-IN')}
          </div>
        </div>

        <div className="mt-2.5 sm:mt-3 pt-2.5 sm:pt-3 border-t border-[#DDE9DF] flex items-center justify-between gap-2 text-xs text-[#5E6C64]">
          <span className="font-medium truncate">In store catalog</span>
          <button
            onClick={() => setActivePage('inventory')}
            className="text-[#23866A] hover:underline font-bold inline-flex items-center gap-1 cursor-pointer shrink-0 min-h-[36px]"
          >
            <span>Stock</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

    </div>
  );
};
