import React, { useState, useEffect } from 'react';
import {
  Store,
  Sliders,
  Info,
  ChevronRight,
  LogOut,
  PhoneCall,
  Bell,
  Globe,
  ScanLine,
  Check,
  TrendingUp,
  Package,
  Layers,
  Smartphone
} from 'lucide-react';

import { PageHeader } from '../components/PageHeader';
import { LanguageSelectorModal } from '../components/LanguageSelectorModal';
import type { PageRoute } from '../types';
import { useLanguage } from '../i18n/LanguageContext';
import { notificationsApi, type NotificationPreferences } from '../api/notifications';

interface SettingsProps {
  shopName: string;
  setActivePage: (page: PageRoute) => void;
  onLogout: () => void;
}

export const Settings: React.FC<SettingsProps> = ({
  shopName,
  setActivePage,
  onLogout,
}) => {
  const { t, currentLanguageMeta } = useLanguage();
  const [isLangModalOpen, setIsLangModalOpen] = useState(false);

  // Notification Preferences State
  const [prefs, setPrefs] = useState<NotificationPreferences>({
    sales_alerts: true,
    inventory_alerts: true,
    system_alerts: true,
    in_app_enabled: true,
    push_enabled: true,
    daily_summary_enabled: true
  });
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [prefSuccess, setPrefSuccess] = useState(false);

  useEffect(() => {
    notificationsApi.getPreferences()
      .then((data) => setPrefs(data))
      .catch((err) => console.warn('Could not load preferences:', err));
  }, []);

  const handleTogglePref = async (key: keyof NotificationPreferences) => {
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    setSavingPrefs(true);
    try {
      await notificationsApi.updatePreferences(updated);
      setPrefSuccess(true);
      setTimeout(() => setPrefSuccess(false), 2000);
    } catch (err) {
      console.warn('Failed to save preferences:', err);
    } finally {
      setSavingPrefs(false);
    }
  };

  return (
    <div className="space-y-5 sm:space-y-6 max-w-2xl mx-auto min-w-0 font-sans pb-12">
      <PageHeader
        title={t('settings.title')}
        description={t('settings.description')}
      />

      {/* 1. Shop Profile Card */}
      <div className="bg-white rounded-2xl p-5 border border-[#DDE9DF] shadow-card flex items-center gap-4">
        <div className="w-14 h-14 rounded-xl bg-[#153D32] text-white flex items-center justify-center font-bold text-xl shadow-xs shrink-0">
          <Store className="w-7 h-7 text-[#FAF8F2]" />
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-[10px] font-bold uppercase tracking-wider text-[#153D32] bg-[#E7F3EE] px-2.5 py-0.5 rounded-full border border-[#23866A]/30">
            {t('settings.profileBadge')}
          </span>
          <h2 className="text-xl font-black text-[#153D32] truncate mt-1">
            {shopName}
          </h2>
          <p className="text-xs text-[#5E6C64] font-medium truncate">
            {t('settings.partnerId')}
          </p>
        </div>
      </div>

      {/* 2. Language Selection Card */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] shadow-card overflow-hidden">
        <div className="p-3.5 bg-[#FAF8F2] text-xs font-semibold text-[#5E6C64] uppercase tracking-wider border-b border-[#DDE9DF]">
          {t('settings.language')}
        </div>

        <button
          onClick={() => setIsLangModalOpen(true)}
          className="w-full p-4 flex items-center justify-between hover:bg-[#FAF8F2]/60 text-left transition-colors cursor-pointer group"
        >
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Globe className="w-5 h-5 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm sm:text-base flex items-center gap-2">
                <span>{t('settings.language')}</span>
                <span className="text-xs font-bold text-[#153D32] bg-[#E7F3EE] px-2 py-0.5 rounded-md border border-[#23866A]/30">
                  {currentLanguageMeta.nativeName}
                </span>
              </p>
              <p className="text-xs text-[#5E6C64] font-normal">
                {t('settings.languageSub')}
              </p>
            </div>
          </div>
          <ChevronRight className="w-5 h-5 text-[#5E6C64] group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>

      {/* 3. Smart Notification Preferences (Section 11) */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] shadow-card divide-y divide-[#DDE9DF] overflow-hidden">
        <div className="p-3.5 bg-[#FAF8F2] flex items-center justify-between border-b border-[#DDE9DF]">
          <span className="text-xs font-bold text-[#153D32] uppercase tracking-wider flex items-center gap-2">
            <Bell className="w-4 h-4 text-[#23866A]" />
            Smart Notification Preferences
          </span>
          {savingPrefs ? (
            <span className="text-[11px] font-bold text-[#5E6C64]">Saving...</span>
          ) : prefSuccess ? (
            <span className="text-[11px] font-bold text-[#23866A] flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> Saved
            </span>
          ) : null}
        </div>

        {/* Inventory Notifications Toggle */}
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0">
              <Package className="w-4 h-4 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm">Inventory Alerts</p>
              <p className="text-xs text-[#5E6C64]">Low stock, out of stock, and reorder warnings</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => handleTogglePref('inventory_alerts')}
            className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors ${
              prefs.inventory_alerts ? 'bg-[#23866A]' : 'bg-[#DDE9DF]'
            }`}
          >
            <div
              className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                prefs.inventory_alerts ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {/* Sales Notifications Toggle */}
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0">
              <TrendingUp className="w-4 h-4 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm">Sales Insights & Summaries</p>
              <p className="text-xs text-[#5E6C64]">Daily revenue summary and significant sales trends</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => handleTogglePref('sales_alerts')}
            className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors ${
              prefs.sales_alerts ? 'bg-[#23866A]' : 'bg-[#DDE9DF]'
            }`}
          >
            <div
              className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                prefs.sales_alerts ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {/* System Notifications Toggle */}
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-[#FAF8F2] text-[#252D29] flex items-center justify-center shrink-0">
              <Layers className="w-4 h-4 text-[#153D32]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm">System & Invoice Confirmations</p>
              <p className="text-xs text-[#5E6C64]">Invoice scanning progress and batch updates</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => handleTogglePref('system_alerts')}
            className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors ${
              prefs.system_alerts ? 'bg-[#23866A]' : 'bg-[#DDE9DF]'
            }`}
          >
            <div
              className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                prefs.system_alerts ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {/* Push Notifications Toggle */}
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0">
              <Smartphone className="w-4 h-4 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm">Mobile Push Notifications</p>
              <p className="text-xs text-[#5E6C64]">Deliver high-priority alerts directly to your mobile device</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => handleTogglePref('push_enabled')}
            className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors ${
              prefs.push_enabled ? 'bg-[#23866A]' : 'bg-[#DDE9DF]'
            }`}
          >
            <div
              className={`bg-white w-4 h-4 rounded-full shadow-md transform transition-transform ${
                prefs.push_enabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {/* 4. Quick Tools List */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] shadow-card divide-y divide-[#DDE9DF] overflow-hidden">
        <div className="p-3.5 bg-[#FAF8F2] text-xs font-semibold text-[#5E6C64] uppercase tracking-wider border-b border-[#DDE9DF]">
          {t('settings.quickTools')}
        </div>

        <button
          onClick={() => setActivePage('scanner')}
          className="w-full p-4 flex items-center justify-between hover:bg-[#FAF8F2]/60 text-left transition-colors cursor-pointer group"
        >
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-[#FBF4E7] text-[#D6AE62] flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <ScanLine className="w-5 h-5 text-[#A07828]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm sm:text-base">Invoice Intelligence Scanner</p>
              <p className="text-xs text-[#5E6C64] font-normal">Extract supplier invoices & auto-update shelves</p>
            </div>
          </div>
          <ChevronRight className="w-5 h-5 text-[#5E6C64] group-hover:translate-x-0.5 transition-transform" />
        </button>

        <button
          onClick={() => setActivePage('insights')}
          className="w-full p-4 flex items-center justify-between hover:bg-[#FAF8F2]/60 text-left transition-colors cursor-pointer group"
        >
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
              <Sliders className="w-5 h-5 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm sm:text-base">{t('insights.title')}</p>
              <p className="text-xs text-[#5E6C64] font-normal">{t('insights.description')}</p>
            </div>
          </div>
          <ChevronRight className="w-5 h-5 text-[#5E6C64] group-hover:translate-x-0.5 transition-transform" />
        </button>
      </div>

      {/* 5. Help & About */}
      <div className="bg-white rounded-2xl border border-[#DDE9DF] shadow-card divide-y divide-[#DDE9DF] overflow-hidden">
        <div className="p-3.5 bg-[#FAF8F2] text-xs font-semibold text-[#5E6C64] uppercase tracking-wider border-b border-[#DDE9DF]">
          {t('settings.helpInfo')}
        </div>

        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-[#E7F3EE] text-[#153D32] flex items-center justify-center shrink-0">
              <PhoneCall className="w-5 h-5 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm sm:text-base">{t('settings.supportLine')}</p>
              <p className="text-xs text-[#5E6C64] font-normal">Toll-free 24/7 hotline: 1800-SHELFORA</p>
            </div>
          </div>
          <span className="text-xs font-bold text-[#153D32] bg-[#E7F3EE] px-3 py-1 rounded-xl border border-[#23866A]/30">
            24/7 Support
          </span>
        </div>

        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-[#FAF8F2] text-[#252D29] flex items-center justify-center shrink-0">
              <Info className="w-5 h-5 text-[#23866A]" />
            </div>
            <div>
              <p className="font-bold text-[#252D29] text-sm sm:text-base">{t('settings.appVersion')}</p>
              <p className="text-xs text-[#5E6C64] font-normal">Shelfora Grocery Intelligence Platform v2.0 (Multi-Language)</p>
            </div>
          </div>
          <span className="text-xs font-bold text-[#5E6C64] bg-[#FAF8F2] px-3 py-1 rounded-xl border border-[#DDE9DF]">
            v2.0.0
          </span>
        </div>
      </div>

      {/* Logout Action */}
      <button
        onClick={onLogout}
        className="w-full py-3.5 px-6 rounded-xl bg-[#FDF1EF] hover:bg-[#F9E2DD] border border-[#EF806D]/30 text-[#EF806D] font-bold text-base flex items-center justify-center gap-2 transition-colors cursor-pointer shadow-card active:scale-[0.99]"
      >
        <LogOut className="w-5 h-5 text-[#EF806D]" />
        <span>{t('settings.logOut')}</span>
      </button>

      <LanguageSelectorModal
        isOpen={isLangModalOpen}
        onClose={() => setIsLangModalOpen(false)}
      />
    </div>
  );
};

export default Settings;
