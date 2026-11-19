import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../../../src/index.css';
import { LanguageProvider } from '../../../src/i18n/LanguageContext';
import { AuthContext } from '../../../src/context/authContextDef';
import type { AuthContextType } from '../../../src/context/AuthContext';
import { Sales } from '../../../src/pages/Sales';
import { fetchProducts } from '../../../src/services/inventoryService';
import type { Product } from '../../../src/types';

// No Firebase in the test harness: a signed-out auth context; API calls use the backend token
const unavailable = () => Promise.reject(new Error('Not available in the test harness'));
const harnessAuth = {
  firebaseUser: null, userProfile: null, user: null, loading: false, error: null,
  login: unavailable, loginDemo: unavailable, loginWithGoogle: unavailable, register: unavailable, logout: unavailable,
  resetPassword: unavailable, refreshProfile: unavailable, updateProfile: unavailable, setLanguage: unavailable, setTheme: unavailable,
} as unknown as AuthContextType;

// Loads the shop's real products from the test backend, then mounts the real Sales page.
export function Harness() {
  const [products, setProducts] = useState<Product[] | null>(null);
  useEffect(() => {
    fetchProducts().then(setProducts).catch(() => setProducts([]));
  }, []);
  if (!products) return <p>Loading products…</p>;
  return <Sales products={products} shopName="E2E Shop" />;
}

createRoot(document.getElementById('root')!).render(
  <AuthContext.Provider value={harnessAuth}>
    <LanguageProvider>
      <Harness />
    </LanguageProvider>
  </AuthContext.Provider>,
);
