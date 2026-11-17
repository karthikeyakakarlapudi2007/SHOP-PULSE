import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Camera,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  ImagePlus,
  Loader2,
  RefreshCcw,
  RotateCcw,
  RotateCw,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
import {
  documentPrepApi,
  pageImageUrl,
  type DocumentSource,
  type PrepExtractResult,
  type PrepSession,
  type PreparedPage,
  type VariantName,
} from '../../api/documentPrep';
import { AuthImage } from './AuthImage';
import { CameraCapture } from './CameraCapture';
import {
  WORKFLOW_STEPS,
  canUseLiveCamera,
  describeCorrections,
  gradeInfo,
  moveItem,
  outlinePoints,
  validatePhotoFile,
  workflowStepIndex,
  type WorkflowPhase,
} from './prepHelpers';

interface PendingUpload {
  tempId: string;
  name: string;
  blob: Blob;
  status: 'waiting' | 'uploading' | 'processing' | 'error';
  progress: number | null;
  error?: string;
  /** When retaking, the page this photo replaces. */
  replaces?: string;
}

interface DocumentPrepWorkflowProps {
  onExtracted: (result: PrepExtractResult) => void;
  onUseDirectUpload: () => void;
}

const btnPrimary =
  'inline-flex items-center justify-center gap-2 min-h-12 px-5 rounded-xl bg-[#153D32] hover:bg-[#0F2D25] text-white text-sm font-bold disabled:opacity-50 cursor-pointer transition-colors';
const btnSecondary =
  'inline-flex items-center justify-center gap-2 min-h-12 px-4 rounded-xl border border-[#DDE9DF] bg-white hover:bg-[#FAF8F2] text-sm font-semibold text-[#153D32] disabled:opacity-50 cursor-pointer transition-colors';
const btnTool =
  'inline-flex flex-col items-center justify-center gap-1 min-h-14 min-w-[4.5rem] px-2 rounded-xl border border-[#DDE9DF] bg-white hover:bg-[#FAF8F2] text-[11px] font-semibold text-[#153D32] disabled:opacity-50 cursor-pointer transition-colors';

const Stepper: React.FC<{ active: number; activeEnd?: number }> = ({ active, activeEnd }) => {
  const end = activeEnd ?? active;
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2" aria-label="Scanning steps">
      {WORKFLOW_STEPS.map((label, i) => {
        const state = i < active ? 'done' : i <= end ? 'active' : 'todo';
        return (
          <li
            key={label}
            aria-current={state === 'active' ? 'step' : undefined}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border ${
              state === 'done'
                ? 'bg-[#E7F6F1] border-[#23866A]/30 text-[#16704F]'
                : state === 'active'
                ? 'bg-[#153D32] border-[#153D32] text-white'
                : 'bg-white border-[#DDE9DF] text-[#5E6C64]'
            } ${state === 'todo' ? 'hidden sm:flex' : 'flex'}`}
          >
            <span className="tabular-nums">{i + 1}</span>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
};

let tempCounter = 0;

export const DocumentPrepWorkflow: React.FC<DocumentPrepWorkflowProps> = ({ onExtracted, onUseDirectUpload }) => {
  const [session, setSession] = useState<PrepSession | null>(null);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [phase, setPhase] = useState<WorkflowPhase>('capture');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [retakeTarget, setRetakeTarget] = useState<string | null>(null);
  const [mobileView, setMobileView] = useState<'prepared' | 'original'>('prepared');
  const [imageVersion, setImageVersion] = useState(0);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const cameraInputRef = useRef<HTMLInputElement | null>(null);
  const sessionRef = useRef<PrepSession | null>(null);
  const processingRef = useRef(false);
  const pendingRef = useRef<PendingUpload[]>([]);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const pages = session?.pages ?? [];
  const maxPages = session?.limits.max_pages ?? 10;
  const selected = pages.find((p) => p.page_id === selectedId) ?? pages[0] ?? null;
  const activeUploads = pending.filter((p) => p.status !== 'error');

  // Clean up the server-side session if the user leaves without reading the invoice
  useEffect(() => {
    return () => {
      const s = sessionRef.current;
      if (s && !s.pages.length) documentPrepApi.deleteSession(s.session_id).catch(() => undefined);
    };
  }, []);

  const ensureSession = useCallback(async (): Promise<PrepSession> => {
    if (sessionRef.current) return sessionRef.current;
    const created = await documentPrepApi.createSession();
    sessionRef.current = created;
    setSession(created);
    return created;
  }, []);

  const updatePending = (tempId: string, patch: Partial<PendingUpload>) =>
    setPending((list) => list.map((p) => (p.tempId === tempId ? { ...p, ...patch } : p)));

  /** Upload queued photos one at a time so pages keep the order they were taken in. */
  const processQueue = useCallback(async () => {
    if (processingRef.current) return;
    processingRef.current = true;
    try {
      for (;;) {
        const next = pendingRef.current.find((p) => p.status === 'waiting');
        if (!next) break;
        setPhase('processing');
        updatePending(next.tempId, { status: 'uploading', progress: 0 });
        pendingRef.current = pendingRef.current.map((p) => (p.tempId === next.tempId ? { ...p, status: 'uploading' } : p));
        try {
          const s = await ensureSession();
          const page = await documentPrepApi.addPage(s.session_id, next.blob, next.name, {
            onUploadProgress: (pr) => updatePending(next.tempId, { progress: pr.percent }),
            onUploadComplete: () => updatePending(next.tempId, { status: 'processing', progress: null }),
          });
          let latest = await documentPrepApi.getSession(s.session_id);
          if (next.replaces) {
            const oldIndex = latest.pages.findIndex((p) => p.page_id === next.replaces);
            if (oldIndex >= 0) {
              const ids = latest.pages.map((p) => p.page_id);
              const reordered = moveItem(ids, ids.indexOf(page.page_id), oldIndex);
              latest = await documentPrepApi.reorder(s.session_id, reordered);
              latest = await documentPrepApi.deletePage(s.session_id, next.replaces);
            }
          }
          sessionRef.current = latest;
          setSession(latest);
          setSelectedId(page.page_id);
          setPending((list) => list.filter((p) => p.tempId !== next.tempId));
          pendingRef.current = pendingRef.current.filter((p) => p.tempId !== next.tempId);
        } catch (err: any) {
          const message = err?.message || 'The photo could not be processed.';
          updatePending(next.tempId, { status: 'error', error: message, progress: null });
          pendingRef.current = pendingRef.current.map((p) =>
            p.tempId === next.tempId ? { ...p, status: 'error', error: message } : p,
          );
        }
      }
    } finally {
      processingRef.current = false;
      setPhase(sessionRef.current?.pages.length ? 'review' : 'capture');
    }
  }, [ensureSession]);

  const enqueue = useCallback(
    (items: { blob: Blob; name: string }[], replaces?: string) => {
      const added: PendingUpload[] = items.map((it) => ({
        tempId: `tmp-${Date.now()}-${tempCounter++}`,
        name: it.name,
        blob: it.blob,
        status: 'waiting',
        progress: null,
        replaces,
      }));
      pendingRef.current = [...pendingRef.current, ...added];
      setPending((list) => [...list, ...added]);
      void processQueue();
    },
    [processQueue],
  );

  const capacityLeft = () => maxPages - pages.length - activeUploads.length + (retakeTarget ? 1 : 0);

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList || !fileList.length) return;
    setError(null);
    const files = Array.from(fileList);
    const problems: string[] = [];
    const ok: { blob: Blob; name: string }[] = [];
    for (const f of files) {
      const problem = validatePhotoFile(f, session?.limits.max_upload_mb ?? 25);
      if (problem) problems.push(problem);
      else ok.push({ blob: f, name: f.name });
    }
    const room = capacityLeft();
    if (ok.length > room) {
      problems.push(`Only ${Math.max(0, room)} more page(s) can be added (maximum ${maxPages}).`);
      ok.splice(Math.max(0, room));
    }
    if (problems.length) setError(problems.join(' '));
    if (ok.length) {
      enqueue(retakeTarget ? ok.slice(0, 1) : ok, retakeTarget ?? undefined);
      setRetakeTarget(null);
    }
  };

  const handleCapture = useCallback(
    (blob: Blob) => {
      const name = `invoice-page-${Date.now()}.jpg`;
      if (retakeTarget) {
        enqueue([{ blob, name }], retakeTarget);
        setRetakeTarget(null);
        setCameraOpen(false);
      } else {
        enqueue([{ blob, name }]);
      }
    },
    [enqueue, retakeTarget],
  );

  const openCamera = (forRetake?: string) => {
    setError(null);
    setRetakeTarget(forRetake ?? null);
    if (canUseLiveCamera()) setCameraOpen(true);
    else cameraInputRef.current?.click();
  };

  const withBusy = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (err: any) {
      setError(err?.message || 'Something went wrong. Please try again.');
    } finally {
      setBusy(null);
    }
  };

  const replacePage = (updated: PreparedPage) => {
    setSession((s) => (s ? { ...s, pages: s.pages.map((p) => (p.page_id === updated.page_id ? updated : p)) } : s));
    setImageVersion((v) => v + 1);
  };

  const rotate = (page: PreparedPage, change: { rotate_by?: -90 | 90 | 180; rotation?: 0 }) =>
    withBusy('rotate', async () => {
      replacePage(await documentPrepApi.updatePage(session!.session_id, page.page_id, change));
    });

  const selectVariant = (page: PreparedPage, variant: VariantName) =>
    withBusy('variant', async () => {
      replacePage(await documentPrepApi.updatePage(session!.session_id, page.page_id, { selected_variant: variant }));
    });

  const reprocessWithoutAuto = (page: PreparedPage) =>
    withBusy('reprocess', async () => {
      replacePage(
        await documentPrepApi.reprocessPage(session!.session_id, page.page_id, {
          auto_orientation: false,
          perspective: false,
        }),
      );
    });

  const reprocessAuto = (page: PreparedPage) =>
    withBusy('reprocess', async () => {
      replacePage(await documentPrepApi.reprocessPage(session!.session_id, page.page_id, {}));
    });

  const removePage = (page: PreparedPage) =>
    withBusy('remove', async () => {
      const latest = await documentPrepApi.deletePage(session!.session_id, page.page_id);
      setSession(latest);
      if (selectedId === page.page_id) setSelectedId(latest.pages[0]?.page_id ?? null);
      if (!latest.pages.length) setPhase('capture');
    });

  const movePage = (index: number, delta: number) =>
    withBusy('reorder', async () => {
      const ids = moveItem(pages.map((p) => p.page_id), index, index + delta);
      setSession((s) => (s ? { ...s, pages: ids.map((id, i) => ({ ...s.pages.find((p) => p.page_id === id)!, index: i })) } : s));
      setSession(await documentPrepApi.reorder(session!.session_id, ids));
    });

  const downloadPdf = (source: DocumentSource) =>
    withBusy('pdf', async () => {
      setPhase('pdf');
      try {
        const blob = await documentPrepApi.downloadPdf(session!.session_id, source);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = source === 'original' ? 'invoice-original-photos.pdf' : 'invoice-scan.pdf';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 2000);
      } finally {
        setPhase('review');
      }
    });

  const readInvoice = (source: DocumentSource) =>
    withBusy('ocr', async () => {
      setPhase('pdf');
      try {
        await new Promise((r) => window.setTimeout(r, 0));
        setPhase('ocr');
        const result = await documentPrepApi.extract(session!.session_id, source);
        setPhase('done');
        onExtracted(result);
      } catch (err) {
        setPhase('review');
        throw err;
      }
    });

  const stepIndex = workflowStepIndex(phase);
  const stepEnd = phase === 'processing' ? 3 : undefined;
  const anyRetake = pages.some((p) => p.retake_recommended);
  const uncertain = pages.filter((p) => p.needs_confirmation);

  return (
    <div className="space-y-4">
      <div className="bg-white p-4 sm:p-5 rounded-2xl border border-[#DDE9DF] shadow-card space-y-4">
        <Stepper active={stepIndex} activeEnd={stepEnd} />

        {/* Capture controls */}
        <div className="flex flex-col sm:flex-row gap-2.5">
          <button type="button" className={`${btnPrimary} sm:flex-1`} onClick={() => openCamera()} disabled={capacityLeft() <= 0 || !!busy}>
            <Camera className="w-5 h-5 text-[#D6AE62]" aria-hidden="true" />
            {pages.length ? 'Add page with camera' : 'Open camera'}
          </button>
          <button type="button" className={`${btnSecondary} sm:flex-1`} onClick={() => fileInputRef.current?.click()} disabled={capacityLeft() <= 0 || !!busy}>
            <ImagePlus className="w-5 h-5 text-[#23866A]" aria-hidden="true" />
            Choose photos
          </button>
          <button type="button" className={`${btnSecondary} sm:w-auto`} onClick={onUseDirectUpload}>
            <FileText className="w-5 h-5 text-[#5E6C64]" aria-hidden="true" />
            Upload PDF or file
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/heic,image/heif,image/webp,image/bmp,image/tiff,.jpg,.jpeg,.png,.heic,.heif,.webp,.bmp,.tif,.tiff"
            className="hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = '';
            }}
          />
          {/* Native camera fallback (phones without live camera access, Android WebView) */}
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => {
              handleFiles(e.target.files);
              e.target.value = '';
            }}
          />
        </div>
        {!pages.length && !pending.length && (
          <p className="text-xs text-[#5E6C64]">
            Photograph each page of the invoice. Pages are checked, turned upright, straightened and cleaned automatically.
            You can rotate, retake, remove or reorder pages before reading the invoice. Original photos are always kept.
          </p>
        )}
      </div>

      {error && (
        <div role="alert" className="flex items-start gap-3 p-4 rounded-xl bg-[#FDF1EF] border border-[#EF806D]/30 text-[#B4483A] text-sm">
          <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)} className="cursor-pointer" aria-label="Dismiss">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {(pages.length > 0 || pending.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Page list */}
          <div className="lg:col-span-4 bg-white p-4 rounded-2xl border border-[#DDE9DF] shadow-card">
            <h3 className="text-sm font-bold text-[#153D32] mb-3">
              Pages ({pages.length}
              {activeUploads.length ? ` + ${activeUploads.length} processing` : ''})
            </h3>
            <ul className="flex lg:flex-col gap-3 overflow-x-auto lg:overflow-visible pb-1">
              {pages.map((p, i) => {
                const g = gradeInfo(p.quality_before?.grade);
                const isSel = selected?.page_id === p.page_id;
                return (
                  <li key={p.page_id} className="shrink-0 w-44 lg:w-auto">
                    <div
                      className={`flex lg:flex-row flex-col gap-3 p-2 rounded-xl border ${
                        isSel ? 'border-[#23866A] bg-[#F4FAF7]' : 'border-[#DDE9DF] bg-white'
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => setSelectedId(p.page_id)}
                        className="shrink-0 w-full lg:w-20 h-28 lg:h-24 rounded-lg overflow-hidden bg-[#FAF8F2] border border-[#DDE9DF] flex items-center justify-center cursor-pointer"
                        aria-label={`Show page ${i + 1}`}
                      >
                        <AuthImage
                          src={pageImageUrl(p, p.selected_variant, 'thumb')}
                          version={`${p.manual_rotation}-${p.selected_variant}-${imageVersion}`}
                          alt={`Page ${i + 1}`}
                          className="max-h-28 lg:max-h-24 object-contain"
                        />
                      </button>
                      <div className="flex-1 min-w-0 space-y-1.5">
                        <p className="text-sm font-bold text-[#153D32]">Page {i + 1}</p>
                        <span className={`inline-block px-2 py-0.5 rounded-full border text-[11px] font-bold ${g.badgeClass}`}>{g.label}</span>
                        {p.retake_recommended && <p className="text-[11px] font-semibold text-[#B4483A]">Retake recommended</p>}
                        {p.needs_confirmation && !p.retake_recommended && (
                          <p className="text-[11px] font-semibold text-[#8A6420]">Check it is upright</p>
                        )}
                        <div className="flex gap-1.5 pt-1">
                          <button type="button" className="p-2 rounded-lg border border-[#DDE9DF] hover:bg-[#FAF8F2] disabled:opacity-40 cursor-pointer"
                            onClick={() => movePage(i, -1)} disabled={i === 0 || !!busy} aria-label={`Move page ${i + 1} earlier`}>
                            <ChevronLeft className="w-4 h-4 lg:rotate-90" aria-hidden="true" />
                          </button>
                          <button type="button" className="p-2 rounded-lg border border-[#DDE9DF] hover:bg-[#FAF8F2] disabled:opacity-40 cursor-pointer"
                            onClick={() => movePage(i, 1)} disabled={i === pages.length - 1 || !!busy} aria-label={`Move page ${i + 1} later`}>
                            <ChevronRight className="w-4 h-4 lg:rotate-90" aria-hidden="true" />
                          </button>
                          <button type="button" className="p-2 rounded-lg border border-[#EF806D]/40 text-[#B4483A] hover:bg-[#FDF1EF] disabled:opacity-40 cursor-pointer"
                            onClick={() => removePage(p)} disabled={!!busy} aria-label={`Remove page ${i + 1}`}>
                            <Trash2 className="w-4 h-4" aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </li>
                );
              })}
              {pending.map((u) => (
                <li key={u.tempId} className="shrink-0 w-44 lg:w-auto">
                  <div className="p-3 rounded-xl border border-dashed border-[#DDE9DF] bg-[#FAF8F2] text-xs text-[#5E6C64] space-y-2">
                    {u.status === 'error' ? (
                      <>
                        <p className="font-semibold text-[#B4483A] flex items-center gap-1.5">
                          <AlertTriangle className="w-4 h-4" aria-hidden="true" /> Could not add photo
                        </p>
                        <p>{u.error}</p>
                        <div className="flex gap-2">
                          <button type="button" className="underline cursor-pointer" onClick={() => {
                            updatePending(u.tempId, { status: 'waiting', error: undefined });
                            pendingRef.current = pendingRef.current.map((p) => (p.tempId === u.tempId ? { ...p, status: 'waiting' } : p));
                            void processQueue();
                          }}>Try again</button>
                          <button type="button" className="underline cursor-pointer" onClick={() => {
                            setPending((l) => l.filter((p) => p.tempId !== u.tempId));
                            pendingRef.current = pendingRef.current.filter((p) => p.tempId !== u.tempId);
                          }}>Remove</button>
                        </div>
                      </>
                    ) : (
                      <>
                        <p className="font-semibold text-[#153D32] flex items-center gap-1.5">
                          <Loader2 className="w-4 h-4 animate-spin text-[#23866A]" aria-hidden="true" />
                          {u.status === 'uploading'
                            ? `Uploading${u.progress != null ? ` ${u.progress}%` : '…'}`
                            : u.status === 'processing'
                            ? 'Checking and correcting…'
                            : 'Waiting…'}
                        </p>
                        <p>Quality check · rotation · straightening · enhancement</p>
                      </>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* Page review */}
          <div className="lg:col-span-8 space-y-4">
            {selected && session && (
              <PageReview
                page={selected}
                pageNumber={pages.findIndex((p) => p.page_id === selected.page_id) + 1}
                imageVersion={imageVersion}
                busy={busy}
                mobileView={mobileView}
                setMobileView={setMobileView}
                onRotate={(change) => rotate(selected, change)}
                onSelectVariant={(v) => selectVariant(selected, v)}
                onRetake={() => openCamera(selected.page_id)}
                onRetakeFromFile={() => {
                  setRetakeTarget(selected.page_id);
                  fileInputRef.current?.click();
                }}
                onUndoAuto={() => reprocessWithoutAuto(selected)}
                onRedoAuto={() => reprocessAuto(selected)}
              />
            )}

            {pages.length > 0 && (
              <div className="bg-white p-4 sm:p-5 rounded-2xl border border-[#DDE9DF] shadow-card space-y-3">
                {anyRetake && (
                  <p className="text-xs text-[#B4483A] flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                    Some pages are too unclear to read reliably. Improvements cannot recover detail the camera did not capture;
                    retaking those pages gives the best result.
                  </p>
                )}
                {uncertain.length > 0 && (
                  <p className="text-xs text-[#8A6420] flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                    Please check that page {uncertain.map((p) => pages.indexOf(p) + 1).join(', ')} is upright; the automatic
                    rotation was not certain.
                  </p>
                )}
                <div className="flex flex-col sm:flex-row gap-2.5">
                  <button type="button" className={`${btnPrimary} sm:flex-1`} disabled={!!busy || activeUploads.length > 0} onClick={() => readInvoice('processed')}>
                    {busy === 'ocr' ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> : <CheckCircle2 className="w-5 h-5 text-[#D6AE62]" aria-hidden="true" />}
                    {busy === 'ocr' ? 'Reading invoice…' : `Read invoice (${pages.length} page${pages.length > 1 ? 's' : ''})`}
                    {busy !== 'ocr' && <ArrowRight className="w-4 h-4" aria-hidden="true" />}
                  </button>
                  <button type="button" className={btnSecondary} disabled={!!busy || activeUploads.length > 0} onClick={() => downloadPdf('processed')}>
                    {busy === 'pdf' ? <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" /> : <Download className="w-5 h-5 text-[#23866A]" aria-hidden="true" />}
                    Download PDF
                  </button>
                </div>
                <button type="button" className="text-xs text-[#5E6C64] underline cursor-pointer disabled:opacity-50" disabled={!!busy || activeUploads.length > 0} onClick={() => readInvoice('original')}>
                  Read the original photos instead (without corrections)
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {cameraOpen && (
        <CameraCapture
          onCapture={handleCapture}
          onClose={() => {
            setCameraOpen(false);
            setRetakeTarget(null);
          }}
          onFallback={() => cameraInputRef.current?.click()}
          pagesSoFar={pages.length + activeUploads.length}
          maxPages={retakeTarget ? pages.length + activeUploads.length + 1 : maxPages}
        />
      )}
    </div>
  );
};

interface PageReviewProps {
  page: PreparedPage;
  pageNumber: number;
  imageVersion: number;
  busy: string | null;
  mobileView: 'prepared' | 'original';
  setMobileView: (v: 'prepared' | 'original') => void;
  onRotate: (change: { rotate_by?: -90 | 90 | 180; rotation?: 0 }) => void;
  onSelectVariant: (v: VariantName) => void;
  onRetake: () => void;
  onRetakeFromFile: () => void;
  onUndoAuto: () => void;
  onRedoAuto: () => void;
}

const PageReview: React.FC<PageReviewProps> = ({
  page,
  pageNumber,
  imageVersion,
  busy,
  mobileView,
  setMobileView,
  onRotate,
  onSelectVariant,
  onRetake,
  onRetakeFromFile,
  onUndoAuto,
  onRedoAuto,
}) => {
  const before = gradeInfo(page.quality_before?.grade);
  const after = gradeInfo(page.quality_after?.grade);
  const outline = outlinePoints(page.document?.quad, page.document?.image_size, page.manual_rotation);
  const corrections = describeCorrections(page);
  const autoDisabled = page.steps.some((s) => s.step === 'orientation' && s.reason.includes('disabled'));
  const version = `${page.manual_rotation}-${page.selected_variant}-${imageVersion}`;
  const issues = (page.quality_before?.issues ?? []).filter((i) => i.severity >= 2);

  return (
    <div className="bg-white p-4 sm:p-5 rounded-2xl border border-[#DDE9DF] shadow-card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-bold text-[#153D32]">Page {pageNumber}</h3>
        <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#5E6C64]">
          Quality
          <span className={`px-2 py-0.5 rounded-full border ${before.badgeClass}`}>{before.label}</span>
          <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
          <span className={`px-2 py-0.5 rounded-full border ${after.badgeClass}`}>{after.label}</span>
        </div>
      </div>

      {/* Mobile: one image at a time */}
      <div className="flex sm:hidden rounded-xl border border-[#DDE9DF] p-1 bg-[#FAF8F2]" role="tablist">
        {(['prepared', 'original'] as const).map((v) => (
          <button key={v} type="button" role="tab" aria-selected={mobileView === v}
            onClick={() => setMobileView(v)}
            className={`flex-1 min-h-11 rounded-lg text-sm font-semibold cursor-pointer ${mobileView === v ? 'bg-white text-[#153D32] shadow-xs' : 'text-[#5E6C64]'}`}>
            {v === 'prepared' ? 'Prepared' : 'Original photo'}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <figure className={`${mobileView === 'original' ? 'block' : 'hidden'} sm:block`}>
          <figcaption className="text-xs font-semibold text-[#5E6C64] mb-1.5">
            Original photo{outline ? ' · detected page outline' : ''}
          </figcaption>
          <div className="rounded-xl border border-[#DDE9DF] bg-[#FAF8F2] p-2 flex items-center justify-center min-h-48">
            <AuthImage src={pageImageUrl(page, 'original', 'preview')} version={version} alt={`Original photo of page ${pageNumber}`} className="max-h-[28rem] w-auto object-contain">
              {outline && (
                <svg viewBox={outline.viewBox} preserveAspectRatio="none" className="absolute inset-0 w-full h-full pointer-events-none" aria-hidden="true">
                  <polygon points={outline.points} fill="rgba(35,134,106,0.10)" stroke="#23866A" strokeWidth={Math.max(3, (page.document.image_size?.[0] ?? 1000) / 250)} />
                </svg>
              )}
            </AuthImage>
          </div>
        </figure>
        <figure className={`${mobileView === 'prepared' ? 'block' : 'hidden'} sm:block`}>
          <figcaption className="text-xs font-semibold text-[#5E6C64] mb-1.5">
            Prepared for reading · {page.variants.find((v) => v.name === page.selected_variant)?.label}
          </figcaption>
          <div className="rounded-xl border border-[#DDE9DF] bg-[#FAF8F2] p-2 flex items-center justify-center min-h-48">
            <AuthImage src={pageImageUrl(page, page.selected_variant, 'preview')} version={version} alt={`Prepared page ${pageNumber}`} className="max-h-[28rem] w-auto object-contain" />
          </div>
        </figure>
      </div>

      {/* Manual rotation */}
      <div>
        <p className="text-xs font-semibold text-[#5E6C64] mb-2">Turn the page if it is not upright</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btnTool} disabled={!!busy} onClick={() => onRotate({ rotate_by: -90 })}>
            <RotateCcw className="w-5 h-5" aria-hidden="true" /> Rotate left
          </button>
          <button type="button" className={btnTool} disabled={!!busy} onClick={() => onRotate({ rotate_by: 90 })}>
            <RotateCw className="w-5 h-5" aria-hidden="true" /> Rotate right
          </button>
          <button type="button" className={btnTool} disabled={!!busy} onClick={() => onRotate({ rotate_by: 180 })}>
            <RefreshCcw className="w-5 h-5" aria-hidden="true" /> Rotate 180°
          </button>
          <button type="button" className={btnTool} disabled={!!busy || page.manual_rotation === 0} onClick={() => onRotate({ rotation: 0 })}>
            <Undo2 className="w-5 h-5" aria-hidden="true" /> Reset
          </button>
          <button type="button" className={btnTool} disabled={!!busy} onClick={onRetake}>
            <Camera className="w-5 h-5" aria-hidden="true" /> Retake
          </button>
          <button type="button" className={btnTool} disabled={!!busy} onClick={onRetakeFromFile}>
            <ImagePlus className="w-5 h-5" aria-hidden="true" /> Replace
          </button>
        </div>
      </div>

      {/* Version choice */}
      {page.variants.length > 1 && (
        <div>
          <p className="text-xs font-semibold text-[#5E6C64] mb-2">
            Version sent for reading
            {page.needs_user_choice && <span className="text-[#8A6420]"> · please pick the clearest one</span>}
          </p>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Page version">
            {page.variants.map((v) => (
              <button
                key={v.name}
                type="button"
                role="radio"
                aria-checked={page.selected_variant === v.name}
                disabled={!!busy}
                onClick={() => onSelectVariant(v.name)}
                className={`min-h-11 px-3 rounded-xl border text-xs font-semibold cursor-pointer disabled:opacity-50 ${
                  page.selected_variant === v.name
                    ? 'border-[#153D32] bg-[#153D32] text-white'
                    : 'border-[#DDE9DF] bg-white text-[#153D32] hover:bg-[#FAF8F2]'
                }`}
              >
                {v.label}
                {page.recommended_variant === v.name && <span className="ml-1.5 text-[10px] opacity-80">(recommended)</span>}
              </button>
            ))}
          </div>
          {page.selection?.reason && <p className="text-[11px] text-[#5E6C64] mt-1.5">{page.selection.reason}</p>}
        </div>
      )}

      {/* What happened */}
      <div className="rounded-xl bg-[#FAF8F2] border border-[#DDE9DF] p-3 space-y-1.5">
        <p className="text-xs font-bold text-[#153D32]">What was done</p>
        <ul className="text-xs text-[#252D29] space-y-1">
          {corrections.map((c) => (
            <li key={c} className="flex items-start gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-[#23866A] shrink-0 mt-0.5" aria-hidden="true" />
              {c}
            </li>
          ))}
        </ul>
        {issues.length > 0 && (
          <ul className="text-xs text-[#5E6C64] space-y-0.5 pt-1">
            {issues.map((i) => (
              <li key={i.code}>• {i.message}</li>
            ))}
          </ul>
        )}
        {page.warnings.map((w) => (
          <p key={w} className="text-xs text-[#8A6420]">{w}</p>
        ))}
        {page.retake_recommended && <p className="text-xs font-semibold text-[#B4483A]">{page.quality_before?.summary}</p>}
        <div className="pt-1">
          {autoDisabled ? (
            <button type="button" className="text-xs underline text-[#153D32] cursor-pointer disabled:opacity-50" disabled={!!busy} onClick={onRedoAuto}>
              <ArrowRight className="inline w-3 h-3" aria-hidden="true" /> Turn automatic corrections back on
            </button>
          ) : (
            <button type="button" className="text-xs underline text-[#5E6C64] cursor-pointer disabled:opacity-50" disabled={!!busy} onClick={onUndoAuto}>
              <ArrowLeft className="inline w-3 h-3" aria-hidden="true" /> Undo automatic turning and cropping for this page
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
