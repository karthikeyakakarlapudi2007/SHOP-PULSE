import React from 'react';
import { ShieldAlert, ArrowLeft } from 'lucide-react';
import type { PageRoute } from '../types';

interface UnauthorizedAccessBannerProps {
  page: PageRoute;
  currentRole: string | null;
  onNavigate: (page: PageRoute) => void;
}

export const UnauthorizedAccessBanner: React.FC<UnauthorizedAccessBannerProps> = ({
  page,
  currentRole,
  onNavigate,
}) => {
  const pageDisplayNames: Record<PageRoute, string> = {
    landing: 'Home',
    login: 'Login',
    signup: 'Signup',
    dashboard: 'Shop Dashboard',
    sales: 'Sales & POS Billing',
    inventory: 'Stock Catalog',
    insights: 'Analytics & Insights',
    scanner: 'Invoice Intelligence Scanner',
    settings: 'Settings & Administration',
  };

  const pageTitle = pageDisplayNames[page] || page;

  return (
    <div
      role="alert"
      className="max-w-2xl mx-auto my-8 p-6 sm:p-8 bg-white rounded-2xl border border-rose-200 shadow-card text-center"
    >
      <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-rose-50 border border-rose-200 flex items-center justify-center text-rose-600">
        <ShieldAlert className="w-8 h-8" />
      </div>

      <h2 className="text-xl sm:text-2xl font-black text-[#153D32] mb-2">
        Access Restricted
      </h2>

      <p className="text-sm sm:text-base text-[#5E6C64] mb-4">
        You do not have permission to view <span className="font-bold text-[#252D29]">{pageTitle}</span>.
        This section is restricted to <span className="font-bold text-[#153D32]">Manager</span> and <span className="font-bold text-[#153D32]">Owner</span> roles.
      </p>

      {currentRole && (
        <div className="inline-block px-3 py-1 mb-6 rounded-full bg-slate-100 text-xs font-semibold text-slate-700">
          Your current role: <span className="uppercase font-bold text-rose-600">{currentRole}</span>
        </div>
      )}

      <div>
        <button
          type="button"
          onClick={() => onNavigate('sales')}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#153D32] text-white font-bold text-sm hover:bg-[#1E5646] active:scale-95 transition-all shadow-sm cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Return to POS Billing</span>
        </button>
      </div>
    </div>
  );
};
