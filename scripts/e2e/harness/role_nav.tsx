import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../../../src/index.css';
import { LanguageProvider } from '../../../src/i18n/LanguageContext';
import { AuthContext } from '../../../src/context/authContextDef';
import type { AuthContextType } from '../../../src/context/AuthContext';
import { Sidebar } from '../../../src/components/Sidebar';
import { BottomNav } from '../../../src/components/BottomNav';
import { UnauthorizedAccessBanner } from '../../../src/components/UnauthorizedAccessBanner';
import type { PageRoute } from '../../../src/types';
import type { UserRole } from '../../../src/types/user';

export function RoleNavHarness() {
  const [activePage, setActivePage] = useState<PageRoute>('dashboard');
  const role = (localStorage.getItem('shoppulse_role') || 'owner') as UserRole;

  const authContextValue = {
    firebaseUser: { uid: 'test_uid' } as any,
    userProfile: { role, uid: 'test_uid', email: 'test@example.com' } as any,
    user: { role, uid: 'test_uid', email: 'test@example.com' } as any,
    loading: false,
    error: null,
  } as unknown as AuthContextType;

  return (
    <AuthContext.Provider value={authContextValue}>
      <LanguageProvider>
        <div className="flex min-h-screen bg-slate-50">
          <Sidebar activePage={activePage} setActivePage={setActivePage} />
          <div className="flex-1 p-6">
            <h1 id="active-page-title">Page: {activePage}</h1>
            {role === 'cashier' && (activePage === 'dashboard' || activePage === 'insights') && (
              <UnauthorizedAccessBanner
                page={activePage}
                currentRole={role}
                onNavigate={setActivePage}
              />
            )}
          </div>
          <BottomNav activePage={activePage} setActivePage={setActivePage} />
        </div>
      </LanguageProvider>
    </AuthContext.Provider>
  );
}

createRoot(document.getElementById('root')!).render(<RoleNavHarness />);
