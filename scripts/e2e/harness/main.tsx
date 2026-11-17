import { createRoot } from 'react-dom/client';
import '../../../src/index.css';
import { InvoiceScanner } from '../../../src/pages/InvoiceScanner';

createRoot(document.getElementById('root')!).render(<InvoiceScanner />);
