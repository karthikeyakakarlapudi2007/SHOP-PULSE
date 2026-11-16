import React, { useState } from 'react';
import { AlertTriangle, CheckCircle2, Package, RefreshCw, ArrowUpRight, Check } from 'lucide-react';
import { useLanguage } from '../../i18n/LanguageContext';
import type { Product, PageRoute } from '../../types';

interface AttentionCardProps {
  lowStockItems: Product[];
  onRestock: (productId: string, quantity: number) => Promise<void> | void;
  setActivePage: (page: PageRoute) => void;
}

export const AttentionCard: React.FC<AttentionCardProps> = ({
  lowStockItems,
  onRestock,
  setActivePage,
}) => {
  const { t } = useLanguage();
  const [restockingId, setRestockingId] = useState<string | null>(null);
  const [recentlyRestocked, setRecentlyRestocked] = useState<Record<string, boolean>>({});

  const handleRestockClick = async (item: Product) => {
    try {
      setRestockingId(item.id);
      await onRestock(item.id, 10);
      setRecentlyRestocked((prev) => ({ ...prev, [item.id]: true }));
      setTimeout(() => {
        setRecentlyRestocked((prev) => ({ ...prev, [item.id]: false }));
      }, 2500);
    } catch (err) {
      console.error('Failed to restock item:', err);
    } finally {
      setRestockingId(null);
    }
  };

  const count = lowStockItems.length;

  if (count === 0) {
    return (
      <div className="bg-white rounded-2xl border border-[#DDE9DF] p-4 sm:p-6 shadow-card flex flex-col justify-between h-full transition-all min-w-0">
        <div>
          <div className="flex items-center justify-between gap-2 pb-3 border-b border-[#DDE9DF] flex-wrap sm:flex-nowrap">
            <h2 className="font-extrabold text-[#252D29] text-sm sm:text-base flex items-center gap-2 min-w-0">
              <span className="w-7 h-7 rounded-lg bg-[#E7F3EE] text-[#23866A] flex items-center justify-center shrink-0 border border-[#52745D]/20">
                <CheckCircle2 className="w-4 h-4 text-[#23866A]" />
              </span>
              <span className="truncate">{t('dashboard.needsAttention')}</span>
            </h2>
            <span className="text-xs font-bold text-[#23866A] bg-[#E7F3EE] px-2.5 py-0.5 rounded-full border border-[#52745D]/30 shrink-0">
              Optimal
            </span>
          </div>

          <div className="py-6 sm:py-8 text-center flex flex-col items-center justify-center">
            <div className="w-12 h-12 rounded-2xl bg-[#E7F3EE] text-[#23866A] border border-[#52745D]/25 flex items-center justify-center mb-3">
              <CheckCircle2 className="w-6 h-6" />
            </div>
            <h3 className="font-extrabold text-[#252D29] text-base">
              {t('dashboard.optimalStock')}
            </h3>
            <p className="text-xs text-[#5E6C64] font-medium max-w-xs mt-1">
              {t('dashboard.allStocked')}
            </p>
          </div>
        </div>

        <button
          onClick={() => setActivePage('inventory')}
          className="w-full py-2.5 px-4 bg-[#FAF8F2] hover:bg-[#F3EFE3] text-[#252D29] font-bold text-xs rounded-lg border border-[#DDE9DF] transition-colors flex items-center justify-center gap-1 cursor-pointer min-h-[40px] mt-2"
        >
          <span>{t('nav.stockCatalog')}</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl border border-[#DDE9DF] shadow-card flex flex-col justify-between p-4 sm:p-6 h-full relative transition-all min-w-0">
      <div>
        <div className="flex items-center justify-between gap-2 pb-3 border-b border-[#DDE9DF] flex-wrap sm:flex-nowrap">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div className="w-8 h-8 rounded-lg bg-[#FBF4E7] text-[#A07828] border border-[#D6AE62] flex items-center justify-center shrink-0">
              <AlertTriangle className="w-4 h-4 text-[#A07828]" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="font-extrabold text-[#252D29] text-sm sm:text-base leading-tight truncate">
                {t('dashboard.needsAttention')}
              </h2>
              <p className="text-xs text-[#A07828] font-bold truncate">
                {t('dashboard.itemsRunningLow', { count })}
              </p>
            </div>
          </div>

          <span className="text-xs font-bold text-[#A07828] bg-[#FBF4E7] px-2.5 py-0.5 rounded-full border border-[#D6AE62] shrink-0">
            {count} {t('dashboard.left')}
          </span>
        </div>

        {/* Low Stock Item Cards (Top 3) */}
        <div className="divide-y divide-[#DDE9DF] mt-2 space-y-2">
          {lowStockItems.slice(0, 3).map((item) => {
            const isBusy = restockingId === item.id;
            const isDone = recentlyRestocked[item.id];

            return (
              <div
                key={item.id}
                className="pt-2 first:pt-0 flex items-center justify-between gap-2.5"
              >
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div className="w-8 h-8 sm:w-9 sm:h-9 rounded-lg bg-[#FAF8F2] border border-[#DDE9DF] text-[#5E6C64] flex items-center justify-center shrink-0">
                    <Package className="w-4 h-4 text-[#5E6C64]" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-bold text-[#252D29] text-xs sm:text-sm truncate">
                      {item.name}
                    </p>
                    <div className="flex items-center gap-1.5 sm:gap-2 mt-0.5 flex-wrap">
                      <span className="inline-block text-[10px] sm:text-[11px] font-bold text-[#EF806D] bg-[#FDF1EF] px-2 py-0.5 rounded-md border border-[#EF806D]/20 shrink-0">
                        {item.stock} {item.unit || 'pkts'} {t('dashboard.left')}
                      </span>
                      <span className="text-[10px] sm:text-[11px] text-[#5E6C64] font-medium hidden xs:inline truncate">
                        Min: {item.reorderLevel ?? item.minStock ?? 10}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Restock Button */}
                <button
                  onClick={() => handleRestockClick(item)}
                  disabled={isBusy || isDone}
                  className={`px-3 py-1.5 rounded-lg font-bold text-xs transition-all flex items-center justify-center gap-1.5 cursor-pointer shrink-0 active:scale-95 select-none min-h-[36px] ${
                    isDone
                      ? 'bg-[#23866A] text-white shadow-card'
                      : isBusy
                      ? 'bg-[#E7F3EE] text-[#153D32] opacity-80 cursor-wait'
                      : 'bg-[#153D32] hover:bg-[#0F2D25] text-white shadow-card'
                  }`}
                >
                  {isBusy ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>...</span>
                    </>
                  ) : isDone ? (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      <span>{t('dashboard.restockedSuccess')}</span>
                    </>
                  ) : (
                    <span>{t('dashboard.restock')}</span>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer link to manage full inventory */}
      <div className="pt-3 mt-3 border-t border-[#DDE9DF] flex items-center justify-between gap-2 min-h-[36px]">
        <span className="text-xs text-[#5E6C64] font-medium truncate">
          Priority restock checklist
        </span>
        <button
          onClick={() => setActivePage('inventory')}
          className="text-xs font-bold text-[#153D32] hover:underline flex items-center gap-0.5 cursor-pointer shrink-0 min-h-[32px]"
        >
          <span>{t('dashboard.restockAll')}</span>
          <ArrowUpRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
};
