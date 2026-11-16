import React, { useState } from 'react';
import { UserPlus, ArrowLeft, Globe, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { Button } from '../components/Button';
import { PasswordInput } from '../components/PasswordInput';
import type { PageRoute, BusinessType } from '../types';
import { useLanguage } from '../i18n/LanguageContext';
import { useAuth } from '../hooks/useAuth';
import { LanguageSelectorModal } from '../components/LanguageSelectorModal';
import { ShelforaLogo } from '../components/branding/ShelforaLogo';

interface SignupProps {
  setActivePage: (page: PageRoute) => void;
  onSignupSuccess: (shopName: string) => void;
}

export const Signup: React.FC<SignupProps> = ({ setActivePage, onSignupSuccess }) => {
  const { t, currentLanguageMeta } = useLanguage();
  const { register } = useAuth();
  const [ownerName, setOwnerName] = useState('');
  const [shopName, setShopName] = useState('');
  const [contact, setContact] = useState('');
  const [password, setPassword] = useState('');
  const [businessType, setBusinessType] = useState<BusinessType>('Kirana Store');
  const [isLangModalOpen, setIsLangModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const businessOptions: BusinessType[] = [
    'Kirana Store',
    'Bakery',
    'Pharmacy',
    'Tea Stall',
    'Supermarket',
    'Other',
  ];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMessage(null);

    if (!ownerName.trim()) {
      setError('Please enter the owner name.');
      return;
    }

    if (!shopName.trim()) {
      setError('Please enter your shop name.');
      return;
    }

    // Email / phone validation
    const trimmedContact = contact.trim();
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    let emailToUse = trimmedContact;
    let phoneToUse = '';

    if (emailRegex.test(trimmedContact)) {
      emailToUse = trimmedContact.toLowerCase();
    } else if (/^\d{10}$/.test(trimmedContact)) {
      emailToUse = `${trimmedContact}@shelfora.com`;
      phoneToUse = trimmedContact;
    } else {
      setError('Please enter a valid email address (e.g. store@shelfora.com).');
      return;
    }

    // Password validation (min 6 chars)
    if (!password || password.length < 6) {
      setError('Password must be at least 6 characters long.');
      return;
    }

    try {
      setLoading(true);
      const profile = await register({
        email: emailToUse,
        password,
        displayName: ownerName.trim(),
        ownerName: ownerName.trim(),
        shopName: shopName.trim(),
        phone: phoneToUse,
        businessType,
        language: (currentLanguageMeta.code === 'te' ? 'te' : 'en'),
        theme: 'light',
      });

      setSuccessMessage('Account created successfully! Welcome to Shelfora.');
      onSignupSuccess(profile.shopName || shopName.trim());

      // Redirect smoothly to dashboard
      setTimeout(() => {
        setActivePage('dashboard');
      }, 700);
    } catch (err: any) {
      setError(err.message || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#FAF8F2] flex flex-col justify-center items-center p-4 relative pt-[calc(3.5rem+env(safe-area-inset-top,0px))] pb-[calc(2rem+env(safe-area-inset-bottom,0px))]">

      {/* Top Back Link */}
      <button
        onClick={() => setActivePage('landing')}
        className="fixed sm:absolute top-[calc(1rem+env(safe-area-inset-top,0px))] left-4 sm:top-6 sm:left-6 z-10 flex items-center gap-2 text-sm font-semibold text-[#5E6C64] hover:text-[#153D32] bg-white/90 sm:bg-transparent backdrop-blur-xs px-3 py-1.5 rounded-xl border border-[#DDE9DF] sm:border-transparent transition-colors cursor-pointer min-h-[40px]"
      >
        <ArrowLeft className="w-4 h-4 shrink-0" />
        <span>{t('common.back')}</span>
      </button>

      <div className="max-w-lg w-full bg-white rounded-2xl border border-[#DDE9DF] p-5 sm:p-8 shadow-card my-4 sm:my-8">

        {/* Brand Header */}
        <div className="flex flex-col items-center text-center mb-6">
          <div className="mb-3">
            <ShelforaLogo variant="full" size="lg" showTagline={false} />
          </div>
          <h1 className="text-xl sm:text-2xl font-black text-[#153D32] tracking-tight">{t('auth.createShopAccount')}</h1>
          <p className="text-xs sm:text-sm text-[#5E6C64] font-normal mt-1">{t('auth.signupSub')}</p>

          {/* Initial Onboarding Language Selector */}
          <button
            type="button"
            onClick={() => setIsLangModalOpen(true)}
            className="mt-3 px-3 py-1.5 rounded-full bg-[#E7F3EE] hover:bg-[#B9E5D0]/40 text-[#153D32] border border-[#23866A]/30 text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer min-h-[36px]"
          >
            <Globe className="w-4 h-4 text-[#23866A]" />
            <span>{currentLanguageMeta.nativeName} ({currentLanguageMeta.name})</span>
          </button>
        </div>

        {error && (
          <div role="alert" className="p-3.5 mb-5 rounded-xl bg-[#FDF1EF] border border-[#EF806D]/30 text-[#EF806D] text-xs sm:text-sm font-medium flex items-center gap-2.5">
            <AlertCircle className="w-4 h-4 shrink-0 text-[#EF806D]" />
            <span>{error}</span>
          </div>
        )}

        {successMessage && (
          <div className="p-3.5 mb-5 rounded-xl bg-[#E7F6F1] border border-[#23866A]/30 text-[#23866A] text-xs sm:text-sm font-medium flex items-center gap-2.5">
            <CheckCircle2 className="w-4 h-4 shrink-0 text-[#23866A]" />
            <span>{successMessage}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label htmlFor="signup-owner" className="block text-xs font-bold text-[#153D32] uppercase tracking-wider mb-1">
                {t('auth.ownerName')}
              </label>
              <input
                id="signup-owner"
                type="text"
                required
                disabled={loading}
                autoComplete="name"
                placeholder="Ramesh Gupta"
                value={ownerName}
                onChange={(e) => setOwnerName(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl border border-[#DDE9DF] focus:outline-none focus:ring-2 focus:ring-[#153D32]/20 focus:border-[#153D32] text-base sm:text-sm font-medium text-[#252D29] disabled:bg-[#FAF8F2]/60 disabled:cursor-not-allowed"
              />
            </div>

            <div>
              <label htmlFor="signup-shop" className="block text-xs font-bold text-[#153D32] uppercase tracking-wider mb-1">
                {t('auth.shopName')}
              </label>
              <input
                id="signup-shop"
                type="text"
                required
                disabled={loading}
                autoComplete="organization"
                placeholder="Gupta Kirana Store"
                value={shopName}
                onChange={(e) => setShopName(e.target.value)}
                className="w-full px-4 py-2.5 rounded-xl border border-[#DDE9DF] focus:outline-none focus:ring-2 focus:ring-[#153D32]/20 focus:border-[#153D32] text-base sm:text-sm font-medium text-[#252D29] disabled:bg-[#FAF8F2]/60 disabled:cursor-not-allowed"
              />
            </div>
          </div>

          <div>
            <label htmlFor="signup-business" className="block text-xs font-bold text-[#153D32] uppercase tracking-wider mb-1">
              {t('auth.businessType')}
            </label>
            <select
              id="signup-business"
              value={businessType}
              disabled={loading}
              onChange={(e) => setBusinessType(e.target.value as BusinessType)}
              className="w-full px-4 py-2.5 rounded-xl border border-[#DDE9DF] focus:outline-none focus:ring-2 focus:ring-[#153D32]/20 focus:border-[#153D32] text-base sm:text-sm font-medium text-[#252D29] bg-white disabled:bg-[#FAF8F2]/60 disabled:cursor-not-allowed"
            >
              {businessOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="signup-contact" className="block text-xs font-bold text-[#153D32] uppercase tracking-wider mb-1">
              {t('auth.phoneOrEmail')}
            </label>
            <input
              id="signup-contact"
              type="text"
              required
              disabled={loading}
              autoComplete="email"
              inputMode="email"
              placeholder="store@shelfora.com or 9876543210"
              value={contact}
              onChange={(e) => setContact(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-[#DDE9DF] focus:outline-none focus:ring-2 focus:ring-[#153D32]/20 focus:border-[#153D32] text-base sm:text-sm font-medium text-[#252D29] disabled:bg-[#FAF8F2]/60 disabled:cursor-not-allowed"
            />
          </div>

          <div>
            <label htmlFor="signup-password" className="block text-xs font-bold text-[#153D32] uppercase tracking-wider mb-1">
              {t('auth.createPassword')}
            </label>
            <PasswordInput
              id="signup-password"
              required
              disabled={loading}
              autoComplete="new-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 rounded-xl border border-[#DDE9DF] focus:outline-none focus:ring-2 focus:ring-[#153D32]/20 focus:border-[#153D32] text-base sm:text-sm font-medium text-[#252D29] disabled:bg-[#FAF8F2]/60 disabled:cursor-not-allowed"
            />
          </div>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            disabled={loading}
            className="w-full mt-2 font-bold py-3 bg-[#153D32] hover:bg-[#0F2D25] text-white rounded-xl shadow-card"
            icon={loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <UserPlus className="w-5 h-5" />}
          >
            {loading ? 'Creating Account...' : t('auth.createShopAccount')}
          </Button>
        </form>

        <div className="mt-6 pt-6 border-t border-[#DDE9DF] text-center">
          <p className="text-xs sm:text-sm text-[#5E6C64] font-normal">
            {t('auth.alreadyRegistered')}{' '}
            <button
              onClick={() => setActivePage('login')}
              className="text-[#23866A] font-bold hover:underline cursor-pointer"
            >
              {t('auth.loginHere')}
            </button>
          </p>
        </div>

      </div>

      <LanguageSelectorModal
        isOpen={isLangModalOpen}
        onClose={() => setIsLangModalOpen(false)}
      />
    </div>
  );
};

export default Signup;
