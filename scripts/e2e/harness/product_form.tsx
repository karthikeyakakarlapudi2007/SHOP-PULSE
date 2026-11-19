import { createRoot } from 'react-dom/client';
import '../../../src/index.css';
import { LanguageProvider } from '../../../src/i18n/LanguageContext';
import { AddProductModal } from '../../../src/components/AddProductModal';

// Products the form submitted, read by the browser check (nothing is saved)
const submitted: unknown[] = [];
(window as unknown as { __submitted: unknown[] }).__submitted = submitted;

createRoot(document.getElementById('root')!).render(
  <LanguageProvider>
    <AddProductModal isOpen onClose={() => {}} onAddProduct={(product) => { submitted.push(product); }} />
  </LanguageProvider>,
);
