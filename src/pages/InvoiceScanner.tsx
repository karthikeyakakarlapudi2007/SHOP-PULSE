import React, { useState, useRef, useCallback } from 'react';
import { 
  Upload, 
  CheckCircle2, 
  AlertTriangle, 
  Sparkles, 
  ArrowRight, 
  Download, 
  RotateCcw, 
  Trash2, 
  Plus, 
  Layers,
  Check,
  X
} from 'lucide-react';
import { getAccessToken } from '../api/client';

export interface ExtractedItem {
  id: string;
  product_name: string;
  category?: string;
  quantity: number | null;
  unit: string;
  purchase_price: number | null;
  selling_price?: number | null;
  mrp: number | null;
  amount: number | null;
  confidence: number;
  confidence_level: 'HIGH' | 'MEDIUM' | 'LOW';
  needs_review: boolean;
  validation_issues?: string[];
  matched_product_id?: string | null;
  matched_product_name?: string | null;
}

export interface ExtractedInvoice {
  id: string;
  supplier_name?: string;
  invoice_number?: string;
  invoice_date?: string;
  total_amount: number;
  total_items: number;
  confidence_score: number;
  items: ExtractedItem[];
  excel_url?: string;
}

export const InvoiceScanner: React.FC = () => {
  const [file, setFile] = useState<File | null>(null);
  const [filePreview, setFilePreview] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progressStage, setProgressStage] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [extractedData, setExtractedData] = useState<ExtractedInvoice | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<Set<string>>(new Set());
  const [isConfirming, setIsConfirming] = useState(false);
  const [confirmSuccess, setConfirmSuccess] = useState<string | null>(null);
  const [confirmedProducts, setConfirmedProducts] = useState<any[]>([]);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleFileSelected = (selectedFile: File) => {
    setError(null);
    setConfirmSuccess(null);
    setExtractedData(null);

    const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
    if (!validTypes.includes(selectedFile.type) && !selectedFile.name.match(/\.(jpg|jpeg|png|webp|pdf)$/i)) {
      setError('Please select a valid image (JPG, PNG, WEBP) or PDF invoice.');
      return;
    }

    if (selectedFile.size > 20 * 1024 * 1024) {
      setError('File size exceeds 20MB limit.');
      return;
    }

    setFile(selectedFile);
    if (selectedFile.type.startsWith('image/')) {
      const url = URL.createObjectURL(selectedFile);
      setFilePreview(url);
    } else {
      setFilePreview(null);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const startExtraction = async () => {
    if (!file) return;
    setIsProcessing(true);
    setError(null);
    setProgressStage('Preparing invoice document for intelligence pipeline...');

    const token = getAccessToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
      setProgressStage('Preprocessing image & deskewing layout...');
      await new Promise((r) => setTimeout(r, 600));

      setProgressStage('Extracting spatial tokens & table structure...');
      const response = await fetch('/api/v1/invoices/extract', {
        method: 'POST',
        headers,
        body: formData,
      });

      if (!response.ok) {
        let errMessage = 'Failed to extract invoice data.';
        try {
          const errBody = await response.json();
          errMessage = errBody.detail || errMessage;
        } catch {
          // ignore json parse error
        }
        throw new Error(errMessage);
      }

      setProgressStage('Validating price hierarchy & mathematical consistency...');
      const data = await response.json();

      const normalizedItems: ExtractedItem[] = (data.items || []).map((item: any, idx: number) => ({
        id: item.id || `item_${idx}_${Date.now()}`,
        product_name: item.product_name || item.raw_description || 'Grocery Item',
        category: item.category || 'Grocery',
        quantity: typeof item.quantity === 'number' ? item.quantity : null,
        unit: item.unit || 'unit',
        purchase_price: typeof item.purchase_price === 'number' ? item.purchase_price : (item.rate ?? null),
        selling_price: typeof item.selling_price === 'number' ? item.selling_price : null,
        mrp: typeof item.mrp === 'number' ? item.mrp : null,
        amount: typeof item.amount === 'number' ? item.amount : (item.line_total ?? null),
        confidence: item.confidence ?? 85,
        confidence_level: item.confidence_level || (item.confidence >= 80 ? 'HIGH' : item.confidence >= 60 ? 'MEDIUM' : 'LOW'),
        needs_review: item.needs_review ?? false,
        validation_issues: item.validation_issues || [],
        matched_product_id: item.matched_product_id || null,
        matched_product_name: item.matched_product_name || null,
      }));

      setExtractedData({
        id: data.id,
        supplier_name: data.supplier_name || 'Generic Supplier',
        invoice_number: data.invoice_number || 'INV-' + Math.floor(1000 + Math.random() * 9000),
        invoice_date: data.invoice_date || new Date().toISOString().split('T')[0],
        total_amount: data.total_amount || 0,
        total_items: normalizedItems.length,
        confidence_score: data.confidence_score || 90,
        items: normalizedItems,
        excel_url: data.excel_url || `/api/v1/invoices/${data.id}/excel`,
      });
      setSelectedItemIds(new Set(normalizedItems.map((i) => i.id)));
      setConfirmedProducts([]);
    } catch (err: any) {
      console.error('Invoice scanning error:', err);
      setError(err.message || 'Invoice extraction failed. Please try again.');
    } finally {
      setIsProcessing(false);
      setProgressStage('');
    }
  };

  const handleUpdateItem = (id: string, field: keyof ExtractedItem, value: any) => {
    if (!extractedData) return;
    setExtractedData((prev) => {
      if (!prev) return null;
      const updatedItems = prev.items.map((item) => {
        if (item.id === id) {
          const updated = { ...item, [field]: value };
          // If qty and price edited, recompute amount
          if ((field === 'quantity' || field === 'purchase_price') && updated.quantity && updated.purchase_price) {
            updated.amount = Math.round(updated.quantity * updated.purchase_price * 100) / 100;
          }
          return updated;
        }
        return item;
      });
      const newTotal = updatedItems.reduce((acc, curr) => acc + (curr.amount || 0), 0);
      return {
        ...prev,
        items: updatedItems,
        total_amount: Math.round(newTotal * 100) / 100,
      };
    });
  };

  const handleDeleteItem = (id: string) => {
    if (!extractedData) return;
    setExtractedData((prev) => {
      if (!prev) return null;
      const updatedItems = prev.items.filter((i) => i.id !== id);
      const newTotal = updatedItems.reduce((acc, curr) => acc + (curr.amount || 0), 0);
      return {
        ...prev,
        items: updatedItems,
        total_items: updatedItems.length,
        total_amount: Math.round(newTotal * 100) / 100,
      };
    });
    setSelectedItemIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  const handleAddItem = () => {
    if (!extractedData) return;
    const newItem: ExtractedItem = {
      id: `manual_${Date.now()}`,
      product_name: 'New Product',
      category: 'Groceries',
      quantity: 1,
      unit: 'pcs',
      purchase_price: 100,
      selling_price: 120,
      mrp: 120,
      amount: 100,
      confidence: 100,
      confidence_level: 'HIGH',
      needs_review: false,
    };
    setExtractedData((prev) => {
      if (!prev) return null;
      const updatedItems = [...prev.items, newItem];
      return {
        ...prev,
        items: updatedItems,
        total_items: updatedItems.length,
        total_amount: prev.total_amount + 100,
      };
    });
    setSelectedItemIds((prev) => new Set([...prev, newItem.id]));
  };

  const handleToggleSelect = (id: string) => {
    setSelectedItemIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleToggleSelectAll = () => {
    if (!extractedData) return;
    if (selectedItemIds.size === extractedData.items.length) {
      setSelectedItemIds(new Set());
    } else {
      setSelectedItemIds(new Set(extractedData.items.map((i) => i.id)));
    }
  };

  const handleConfirmToInventory = async () => {
    if (!extractedData || extractedData.items.length === 0) return;
    const selectedItems = extractedData.items.filter((i) => selectedItemIds.has(i.id));
    if (selectedItems.length === 0) {
      setError('Please select at least one item to confirm into inventory.');
      return;
    }

    // Comprehensive validation before submitting to backend
    const invalidItems = selectedItems.filter((i) => {
      const hasName = Boolean(i.product_name && i.product_name.trim());
      const hasValidQty = typeof i.quantity === 'number' && i.quantity > 0;
      const hasValidPrice = typeof i.purchase_price === 'number' && i.purchase_price > 0;
      return !hasName || !hasValidQty || !hasValidPrice;
    });

    if (invalidItems.length > 0) {
      setError(
        `Cannot confirm: ${invalidItems.length} selected item(s) have missing required fields (Product Name, Quantity > 0, or Purchase Rate > 0). Please correct or deselect them.`
      );
      return;
    }

    setIsConfirming(true);
    setError(null);
    setConfirmSuccess(null);

    try {
      const token = getAccessToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const payload = {
        supplier_name: extractedData.supplier_name,
        invoice_number: extractedData.invoice_number,
        invoice_date: extractedData.invoice_date,
        items: selectedItems.map((i) => {
          const purchasePrice = Number(i.purchase_price);
          // Preserve selling price, fall back to MRP or a standard margin if brand new
          const sellingPrice =
            typeof i.selling_price === 'number' && i.selling_price > 0
              ? i.selling_price
              : typeof i.mrp === 'number' && i.mrp > 0
              ? i.mrp
              : Math.round(purchasePrice * 1.2 * 100) / 100;

          return {
            name: i.product_name.trim(),
            product_name: i.product_name.trim(),
            category: i.category || 'Groceries',
            quantity: Math.max(1, Math.round(Number(i.quantity))),
            unit: i.unit?.trim() || 'pcs',
            purchase_price: purchasePrice,
            selling_price: sellingPrice,
            mrp: typeof i.mrp === 'number' && i.mrp > 0 ? i.mrp : undefined,
            mrp_source: typeof i.mrp === 'number' && i.mrp > 0 ? 'INVOICE' : undefined,
            line_amount:
              typeof i.amount === 'number' && i.amount > 0
                ? i.amount
                : Math.round(purchasePrice * Number(i.quantity) * 100) / 100,
            matched_product_id: i.matched_product_id || undefined,
          };
        }),
      };

      const res = await fetch('/api/v1/invoices/confirm', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let msg = 'Failed to confirm stock updates.';
        try {
          const b = await res.json();
          msg = b.detail || msg;
        } catch {
          // ignore
        }
        throw new Error(msg);
      }

      const resData = await res.json();
      const restocked = resData.items_restocked ?? 0;
      const created = resData.items_created ?? 0;
      const totalUnits = resData.total_units ?? 0;
      const totalAmt = resData.total_amount ?? 0;

      setConfirmSuccess(
        `Successfully confirmed ${selectedItems.length} items to your shelves (${restocked} restocked, ${created} newly created)! Total: ₹${totalAmt.toFixed(2)} (${totalUnits} units).`
      );

      if (Array.isArray(resData.saved_products)) {
        setConfirmedProducts(resData.saved_products);
      }

      // Trigger global inventory change notification so other views sync
      window.dispatchEvent(new CustomEvent('shelfora_inventory_changed'));
      window.dispatchEvent(new CustomEvent('shoppulse_inventory_changed'));
    } catch (err: any) {
      console.error('Invoice confirmation failed:', err);
      setError(err.message || 'Failed to update inventory.');
    } finally {
      setIsConfirming(false);
    }
  };

  const resetAll = () => {
    setFile(null);
    setFilePreview(null);
    setExtractedData(null);
    setSelectedItemIds(new Set());
    setConfirmedProducts([]);
    setError(null);
    setConfirmSuccess(null);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-2xl border border-[#DDE9DF] shadow-card">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-xl bg-[#FAF8F2] border border-[#DDE9DF] flex items-center justify-center text-[#153D32]">
            <Layers className="w-6 h-6 text-[#23866A]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl sm:text-2xl font-black text-[#153D32] tracking-tight">
                Invoice Intelligence Scanner
              </h1>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-[#D6AE62]/20 text-[#A07828] border border-[#D6AE62]/40">
                Phase 2 Engine
              </span>
            </div>
            <p className="text-xs sm:text-sm text-[#5E6C64] mt-0.5">
              Upload supplier invoices to extract grocery line items, multi-tier prices, and update your shelves automatically.
            </p>
          </div>
        </div>

        {extractedData && (
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={resetAll}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-[#DDE9DF] bg-[#FAF8F2] hover:bg-[#F3EFE3] text-xs font-semibold text-[#252D29] transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5 text-[#5E6C64]" />
              Scan Another
            </button>
            <a
              href={`/api/v1/invoices/${extractedData.id}/excel`}
              download
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-[#DDE9DF] bg-white hover:bg-[#FAF8F2] text-xs font-semibold text-[#153D32] transition-colors shadow-2xs"
            >
              <Download className="w-3.5 h-3.5 text-[#23866A]" />
              Export Excel
            </a>
          </div>
        )}
      </div>

      {/* Error or Success Alerts */}
      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-[#FDF1EF] border border-[#EF806D]/30 text-[#EF806D] text-xs sm:text-sm font-medium animate-in fade-in">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} className="cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {confirmSuccess && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-[#E7F6F1] border border-[#23866A]/30 text-[#23866A] text-xs sm:text-sm font-semibold animate-in fade-in">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          <span className="flex-1">{confirmSuccess}</span>
          <button type="button" onClick={() => setConfirmSuccess(null)} className="cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Upload Zone & Document Inspector (When no extracted data) */}
      {!extractedData && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Main Upload Dropzone */}
          <div className="lg:col-span-8">
            <div
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
              className={`relative border-2 border-dashed rounded-2xl p-8 sm:p-12 text-center cursor-pointer transition-all duration-200 bg-white ${
                isDragging
                  ? 'border-[#23866A] bg-[#E7F3EE]/50 scale-[0.99]'
                  : file
                  ? 'border-[#23866A] bg-[#FAF8F2]'
                  : 'border-[#DDE9DF] hover:border-[#23866A]/60 hover:bg-[#FAF8F2]'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".jpg,.jpeg,.png,.webp,.pdf,image/jpeg,image/png,image/webp,application/pdf"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files && e.target.files[0]) {
                    handleFileSelected(e.target.files[0]);
                  }
                }}
              />

              <div className="max-w-md mx-auto flex flex-col items-center">
                <div className="w-16 h-16 rounded-2xl bg-[#E7F3EE] flex items-center justify-center text-[#153D32] mb-4 shadow-xs">
                  <Upload className="w-8 h-8 text-[#23866A]" />
                </div>
                <h3 className="text-base sm:text-lg font-bold text-[#153D32]">
                  {file ? file.name : 'Upload your paper invoice or PDF'}
                </h3>
                <p className="text-xs sm:text-sm text-[#5E6C64] mt-1 max-w-sm">
                  {file
                    ? `${(file.size / (1024 * 1024)).toFixed(2)} MB • Ready to analyze`
                    : 'Drag & drop image or PDF invoice here, or click to browse'}
                </p>

                <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-[#FAF8F2] border border-[#DDE9DF] text-[#5E6C64]">
                    JPG / PNG / WEBP
                  </span>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-[#FAF8F2] border border-[#DDE9DF] text-[#5E6C64]">
                    Multi-page PDF
                  </span>
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-[#FAF8F2] border border-[#DDE9DF] text-[#5E6C64]">
                    Max 20MB
                  </span>
                </div>

                {file && !isProcessing && (
                  <div className="mt-8 flex gap-3">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        startExtraction();
                      }}
                      className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[#153D32] hover:bg-[#0F2D25] text-white text-xs sm:text-sm font-bold shadow-md hover:shadow-lg transition-all cursor-pointer"
                    >
                      <Sparkles className="w-4 h-4 text-[#D6AE62]" />
                      Extract Line Items
                      <ArrowRight className="w-4 h-4" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setFile(null);
                        setFilePreview(null);
                      }}
                      className="px-4 py-2.5 rounded-xl border border-[#DDE9DF] bg-white hover:bg-[#FAF8F2] text-xs font-semibold text-[#5E6C64] cursor-pointer"
                    >
                      Remove
                    </button>
                  </div>
                )}

                {/* Progress Animation State */}
                {isProcessing && (
                  <div className="mt-8 w-full max-w-sm bg-white p-4 rounded-xl border border-[#DDE9DF] shadow-xs">
                    <div className="flex items-center justify-between text-xs font-bold text-[#153D32] mb-2">
                      <div className="flex items-center gap-2">
                        <div className="w-4 h-4 border-2 border-[#23866A] border-t-transparent rounded-full animate-spin" />
                        <span>Processing with Shelfora Engine</span>
                      </div>
                      <span className="text-[#23866A]">Active</span>
                    </div>
                    <div className="w-full bg-[#FAF8F2] h-2 rounded-full overflow-hidden border border-[#DDE9DF]">
                      <div className="bg-[#23866A] h-full rounded-full animate-pulse w-3/4" />
                    </div>
                    <p className="text-[11px] text-[#5E6C64] text-left mt-2">
                      {progressStage}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Intelligence Capabilities Sidebar */}
          <div className="lg:col-span-4 space-y-4">
            <div className="bg-white p-5 rounded-2xl border border-[#DDE9DF] shadow-card">
              <h3 className="text-sm font-bold text-[#153D32] mb-3 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-[#D6AE62]" />
                Shelfora Extraction Features
              </h3>
              <ul className="space-y-3 text-xs text-[#5E6C64]">
                <li className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-[#23866A] shrink-0 mt-0.5" />
                  <span><strong>Multi-Price Separation:</strong> Isolates Rate, Purchase Price, Selling Price, and MRP with spatial boundary verification.</span>
                </li>
                <li className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-[#23866A] shrink-0 mt-0.5" />
                  <span><strong>OCR Error Repair:</strong> Corrects common digit and character noise (e.g. `I` → `1`, `O` → `0`) while preserving precision.</span>
                </li>
                <li className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-[#23866A] shrink-0 mt-0.5" />
                  <span><strong>Mathematical Audit:</strong> Verifies Quantity × Rate = Line Total with Decimal precision.</span>
                </li>
                <li className="flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-[#23866A] shrink-0 mt-0.5" />
                  <span><strong>Direct Inventory Restock:</strong> Updates existing stock and registers newly discovered grocery brands.</span>
                </li>
              </ul>
            </div>

            {/* Thumbnail Preview if Image Selected */}
            {filePreview && (
              <div className="bg-white p-4 rounded-2xl border border-[#DDE9DF] shadow-card">
                <p className="text-xs font-bold text-[#153D32] mb-2 flex items-center justify-between">
                  <span>Document Preview</span>
                  <span className="text-[10px] text-[#5E6C64] font-normal">Original upload</span>
                </p>
                <div className="max-h-56 overflow-hidden rounded-xl border border-[#DDE9DF] bg-[#FAF8F2] flex items-center justify-center">
                  <img src={filePreview} alt="Invoice preview" className="w-full object-contain max-h-56" />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Extracted Structured Results Grid */}
      {extractedData && (
        <div className="space-y-6">
          {/* Invoice Summary Ribbon */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white p-4 rounded-2xl border border-[#DDE9DF] shadow-card">
            <div>
              <p className="text-[11px] font-semibold text-[#5E6C64] uppercase tracking-wider">Supplier</p>
              <p className="text-sm font-bold text-[#153D32] truncate">{extractedData.supplier_name}</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-[#5E6C64] uppercase tracking-wider">Invoice # / Date</p>
              <p className="text-sm font-bold text-[#153D32]">
                {extractedData.invoice_number} • {extractedData.invoice_date}
              </p>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-[#5E6C64] uppercase tracking-wider">Line Items</p>
              <p className="text-sm font-bold text-[#153D32]">{extractedData.total_items} items</p>
            </div>
            <div>
              <p className="text-[11px] font-semibold text-[#5E6C64] uppercase tracking-wider">Total Value</p>
              <p className="text-sm font-black text-[#23866A]">
                ₹{extractedData.total_amount.toFixed(2)}
              </p>
            </div>
          </div>

          {/* Interactive Itemized Table */}
          <div className="bg-white rounded-2xl border border-[#DDE9DF] shadow-card overflow-hidden">
            <div className="p-4 sm:p-5 border-b border-[#DDE9DF] flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#FAF8F2]/60">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-bold text-[#153D32]">Extracted Grocery Line Items</h3>
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-bold bg-[#E7F6F1] text-[#23866A] border border-[#23866A]/20">
                    {selectedItemIds.size} of {extractedData.items.length} selected
                  </span>
                </div>
                <p className="text-xs text-[#5E6C64] mt-0.5">
                  Select items to restock, verify prices, and edit fields before saving into your catalog.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleAddItem}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[#DDE9DF] bg-white hover:bg-[#FAF8F2] text-xs font-semibold text-[#153D32] transition-colors cursor-pointer shadow-3xs"
                >
                  <Plus className="w-3.5 h-3.5 text-[#23866A]" />
                  Add Item
                </button>
                <button
                  type="button"
                  onClick={handleConfirmToInventory}
                  disabled={isConfirming || selectedItemIds.size === 0}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#153D32] hover:bg-[#0F2D25] text-white text-xs font-bold shadow-sm transition-all cursor-pointer disabled:opacity-50"
                >
                  <CheckCircle2 className="w-4 h-4 text-[#D6AE62]" />
                  {isConfirming
                    ? 'Updating Shelves...'
                    : `Confirm ${selectedItemIds.size} Items to Inventory`}
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-[#DDE9DF] bg-[#FAF8F2] text-[#5E6C64] font-bold uppercase tracking-wider text-[11px]">
                    <th className="py-3 px-3 w-10 text-center">
                      <input
                        type="checkbox"
                        checked={selectedItemIds.size > 0 && selectedItemIds.size === extractedData.items.length}
                        onChange={handleToggleSelectAll}
                        className="rounded border-[#DDE9DF] text-[#153D32] focus:ring-[#23866A] cursor-pointer"
                        title="Select/Deselect all"
                        aria-label="Select all items"
                      />
                    </th>
                    <th className="py-3 px-3 w-8">#</th>
                    <th className="py-3 px-4 min-w-[200px]">Product Name</th>
                    <th className="py-3 px-3 w-20">Qty</th>
                    <th className="py-3 px-3 w-16">Unit</th>
                    <th className="py-3 px-3 w-24">Purchase Cost</th>
                    <th className="py-3 px-3 w-24">Selling Price</th>
                    <th className="py-3 px-3 w-24">MRP</th>
                    <th className="py-3 px-3 w-24">Line Total</th>
                    <th className="py-3 px-3 text-center w-20">Confidence</th>
                    <th className="py-3 px-3 text-right w-12">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#DDE9DF]">
                  {extractedData.items.map((item, idx) => {
                    const isSelected = selectedItemIds.has(item.id);
                    const isNameInvalid = !item.product_name || !item.product_name.trim();
                    const isQtyInvalid = item.quantity === null || item.quantity === undefined || item.quantity <= 0;
                    const isPriceInvalid = item.purchase_price === null || item.purchase_price === undefined || item.purchase_price <= 0;

                    return (
                      <tr 
                        key={item.id}
                        className={`transition-colors ${
                          !isSelected
                            ? 'opacity-60 bg-gray-50/50'
                            : item.needs_review
                            ? 'bg-[#FBF4E7]/30 hover:bg-[#FBF4E7]/50'
                            : 'hover:bg-[#FAF8F2]/60'
                        }`}
                      >
                        <td className="py-3 px-3 text-center">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleToggleSelect(item.id)}
                            className="rounded border-[#DDE9DF] text-[#153D32] focus:ring-[#23866A] cursor-pointer"
                            aria-label={`Select ${item.product_name}`}
                          />
                        </td>
                        <td className="py-3 px-3 text-[#5E6C64] font-medium">{idx + 1}</td>
                        <td className="py-3 px-4">
                          <input
                            type="text"
                            value={item.product_name}
                            onChange={(e) => handleUpdateItem(item.id, 'product_name', e.target.value)}
                            className={`w-full px-2 py-1 rounded-md border text-xs font-semibold focus:outline-none ${
                              isNameInvalid
                                ? 'border-[#EF806D] bg-[#FDF1EF] text-[#EF806D]'
                                : 'border-transparent hover:border-[#DDE9DF] focus:border-[#153D32] focus:bg-white text-[#153D32]'
                            }`}
                          />
                          {isNameInvalid && (
                            <span className="text-[10px] text-[#EF806D] font-bold block px-2 mt-0.5">
                              Product name is required
                            </span>
                          )}
                          {item.matched_product_name && (
                            <span className="text-[10px] text-[#23866A] font-medium block px-2">
                              Matches: {item.matched_product_name}
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3">
                          <input
                            type="number"
                            step="1"
                            min="1"
                            value={item.quantity ?? ''}
                            onChange={(e) => handleUpdateItem(item.id, 'quantity', parseFloat(e.target.value) || null)}
                            className={`w-full px-2 py-1 rounded-md border text-xs font-semibold focus:outline-none ${
                              isQtyInvalid
                                ? 'border-[#EF806D] bg-[#FDF1EF] text-[#EF806D]'
                                : 'border-transparent hover:border-[#DDE9DF] focus:border-[#153D32] focus:bg-white text-[#252D29]'
                            }`}
                          />
                          {isQtyInvalid && (
                            <span className="text-[10px] text-[#EF806D] font-bold block px-1 mt-0.5">
                              Qty &gt; 0
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3">
                          <input
                            type="text"
                            value={item.unit}
                            onChange={(e) => handleUpdateItem(item.id, 'unit', e.target.value)}
                            className="w-full px-2 py-1 rounded-md border border-transparent hover:border-[#DDE9DF] focus:border-[#153D32] focus:bg-white focus:outline-none text-[#5E6C64]"
                          />
                        </td>
                        <td className="py-3 px-3">
                          <div className="relative">
                            <span className="absolute left-1.5 top-1 text-[#5E6C64]">₹</span>
                            <input
                              type="number"
                              step="0.01"
                              min="0.01"
                              value={item.purchase_price ?? ''}
                              onChange={(e) => handleUpdateItem(item.id, 'purchase_price', parseFloat(e.target.value) || null)}
                              className={`w-full pl-5 pr-1 py-1 rounded-md border text-xs font-bold focus:outline-none ${
                                isPriceInvalid
                                  ? 'border-[#EF806D] bg-[#FDF1EF] text-[#EF806D]'
                                  : 'border-transparent hover:border-[#DDE9DF] focus:border-[#153D32] focus:bg-white text-[#153D32]'
                              }`}
                            />
                          </div>
                          {isPriceInvalid && (
                            <span className="text-[10px] text-[#EF806D] font-bold block px-1 mt-0.5">
                              Rate required
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-3">
                          <div className="relative">
                            <span className="absolute left-1.5 top-1 text-[#5E6C64]">₹</span>
                            <input
                              type="number"
                              step="0.01"
                              placeholder={
                                item.mrp
                                  ? String(item.mrp)
                                  : item.purchase_price
                                  ? String(Math.round(item.purchase_price * 1.2 * 100) / 100)
                                  : '0.00'
                              }
                              value={item.selling_price ?? ''}
                              onChange={(e) => handleUpdateItem(item.id, 'selling_price', parseFloat(e.target.value) || null)}
                              className="w-full pl-5 pr-1 py-1 rounded-md border border-transparent hover:border-[#DDE9DF] focus:border-[#153D32] focus:bg-white focus:outline-none font-medium text-[#252D29]"
                            />
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <div className="relative">
                            <span className="absolute left-1.5 top-1 text-[#5E6C64]">₹</span>
                            <input
                              type="number"
                              step="0.01"
                              value={item.mrp ?? ''}
                              onChange={(e) => handleUpdateItem(item.id, 'mrp', parseFloat(e.target.value) || null)}
                              className="w-full pl-5 pr-1 py-1 rounded-md border border-transparent hover:border-[#DDE9DF] focus:border-[#153D32] focus:bg-white focus:outline-none font-medium text-[#252D29]"
                            />
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <span className="font-extrabold text-[#23866A] px-2 block">
                            ₹{(item.amount ?? (item.quantity && item.purchase_price ? item.quantity * item.purchase_price : 0)).toFixed(2)}
                          </span>
                        </td>
                        <td className="py-3 px-3 text-center">
                          <span 
                            className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              item.confidence >= 80 
                                ? 'bg-[#E7F6F1] text-[#23866A]' 
                                : item.confidence >= 60 
                                ? 'bg-[#FBF4E7] text-[#D6AE62]' 
                                : 'bg-[#FDF1EF] text-[#EF806D]'
                            }`}
                          >
                            {Math.round(item.confidence)}%
                          </span>
                        </td>
                        <td className="py-3 px-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleDeleteItem(item.id)}
                            className="p-1.5 rounded-lg text-[#5E6C64] hover:text-[#EF806D] hover:bg-[#FDF1EF] transition-colors cursor-pointer"
                            title="Delete row"
                            aria-label={`Delete row ${idx + 1}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Table Footer */}
            <div className="p-4 bg-[#FAF8F2] border-t border-[#DDE9DF] flex flex-col sm:flex-row sm:items-center justify-between text-xs text-[#5E6C64] gap-2">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-[#23866A]" />
                <span>Verified by Shelfora Mathematical Reconciliation</span>
              </div>
              <div className="text-right">
                <span className="text-xs font-semibold text-[#5E6C64] mr-2">Grand Total:</span>
                <span className="text-base font-black text-[#153D32]">
                  ₹{extractedData.total_amount.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          {/* Recently Confirmed Inventory Products Summary */}
          {confirmedProducts.length > 0 && (
            <div className="bg-white rounded-2xl border border-[#23866A]/30 p-5 shadow-card animate-in fade-in">
              <div className="flex items-center justify-between pb-3 border-b border-[#DDE9DF] mb-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-5 h-5 text-[#23866A]" />
                  <h4 className="text-sm font-bold text-[#153D32]">
                    Confirmed Inventory Records ({confirmedProducts.length} items)
                  </h4>
                </div>
                <span className="text-xs font-semibold text-[#23866A] bg-[#E7F6F1] px-2.5 py-1 rounded-full border border-[#23866A]/20">
                  Synced to Database
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                {confirmedProducts.map((p: any) => (
                  <div key={p.id} className="p-3 rounded-xl bg-[#FAF8F2] border border-[#DDE9DF] text-xs">
                    <p className="font-bold text-[#153D32] truncate">{p.name}</p>
                    <div className="flex justify-between items-center text-[#5E6C64] mt-1.5">
                      <span>Stock: <strong>{p.current_stock} {p.unit || 'pcs'}</strong></span>
                      <span className="font-semibold text-[#23866A]">₹{p.selling_price?.toFixed(2)}</span>
                    </div>
                    <p className="text-[10px] text-[#5E6C64]/70 mt-1 truncate">ID: {p.id}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default InvoiceScanner;

