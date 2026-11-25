import { useContext, useMemo } from 'react';
import { AuthContext } from '../context/authContextDef';
import type { PageRoute } from '../types';

export type NormalizedRole = 'OWNER' | 'MANAGER' | 'CASHIER';

export interface ShopRoleInfo {
  role: NormalizedRole | null;
  rawRole: string | null;
  isOwner: boolean;
  isManager: boolean;
  isCashier: boolean;
  isStaff: boolean;
  loading: boolean;
  canAccessPage: (page: PageRoute) => boolean;
  canManageStaff: boolean;
  canManageShopSettings: boolean;
  canAccessAnalytics: boolean;
  canAccessPurchases: boolean;
  canAccessSuppliers: boolean;
  canVerifyPricing: boolean;
  canApprovePriceOverrides: boolean;
  canViewPricingAudit: boolean;
  canAccessDashboard: boolean;
  canAccessPos: boolean;
  canAccessInventory: boolean;
}

export function normalizeShopRole(roleStr?: string | null): NormalizedRole | null {
  if (!roleStr) return null;
  const lower = roleStr.trim().toLowerCase();
  if (lower === 'owner') return 'OWNER';
  if (lower === 'manager') return 'MANAGER';
  if (lower === 'cashier' || lower === 'staff') return 'CASHIER';
  return null;
}

export function useShopRole(): ShopRoleInfo {
  const authContext = useContext(AuthContext);
  const userProfile = authContext?.userProfile;
  const loading = authContext?.loading ?? false;

  return useMemo(() => {
    const rawRole = authContext ? (userProfile?.role || null) : 'owner';
    const role = normalizeShopRole(rawRole);

    const isOwner = role === 'OWNER';
    const isManager = role === 'MANAGER';
    const isCashier = role === 'CASHIER';
    const isStaff = isManager || isCashier;

    const canManageStaff = isOwner;
    const canManageShopSettings = isOwner;
    const canAccessAnalytics = isOwner || isManager;
    const canAccessPurchases = isOwner || isManager;
    const canAccessSuppliers = isOwner || isManager;
    const canVerifyPricing = isOwner || isManager;
    const canApprovePriceOverrides = isOwner || isManager;
    const canViewPricingAudit = isOwner || isManager;
    const canAccessDashboard = isOwner || isManager;
    const canAccessPos = isOwner || isManager || isCashier;
    const canAccessInventory = isOwner || isManager || isCashier;

    const canAccessPage = (page: PageRoute): boolean => {
      switch (page) {
        case 'landing':
        case 'login':
        case 'signup':
          return true;
        case 'dashboard':
          return canAccessDashboard;
        case 'sales':
          return canAccessPos;
        case 'inventory':
          return canAccessInventory;
        case 'insights':
          return canAccessAnalytics;
        case 'scanner':
          return canAccessPurchases;
        case 'settings':
          return isOwner || isManager;
        default:
          return false;
      }
    };

    return {
      role,
      rawRole,
      isOwner,
      isManager,
      isCashier,
      isStaff,
      loading,
      canAccessPage,
      canManageStaff,
      canManageShopSettings,
      canAccessAnalytics,
      canAccessPurchases,
      canAccessSuppliers,
      canVerifyPricing,
      canApprovePriceOverrides,
      canViewPricingAudit,
      canAccessDashboard,
      canAccessPos,
      canAccessInventory,
    };
  }, [authContext, userProfile?.role, loading]);
}

