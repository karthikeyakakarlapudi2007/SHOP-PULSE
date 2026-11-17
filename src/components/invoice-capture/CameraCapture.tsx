import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, X, Check, AlertTriangle, ImagePlus } from 'lucide-react';
import { cameraErrorMessage, canUseLiveCamera } from './prepHelpers';

interface CameraCaptureProps {
  /** Called once per captured page with a full-resolution JPEG. */
  onCapture: (photo: Blob) => void;
  onClose: () => void;
  /** Fallback when the live camera cannot be used: open the phone camera / file picker. */
  onFallback: () => void;
  pagesSoFar: number;
  maxPages: number;
}

/**
 * Full-screen camera for photographing invoice pages one after another.
 * Uses the rear camera at the highest resolution the device offers. Every capture is
 * handed to the parent immediately so pages are processed while the next one is taken.
 */
export const CameraCapture: React.FC<CameraCaptureProps> = ({ onCapture, onClose, onFallback, pagesSoFar, maxPages }) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(() =>
    canUseLiveCamera()
      ? null
      : cameraErrorMessage({ name: typeof window !== 'undefined' && window.isSecureContext === false ? 'InsecureContext' : 'Unsupported' }),
  );
  const [flash, setFlash] = useState(false);
  const [busy, setBusy] = useState(false);
  const atLimit = pagesSoFar >= maxPages;

  useEffect(() => {
    let cancelled = false;
    if (!canUseLiveCamera()) return;
    navigator.mediaDevices
      .getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } },
      })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          video.onloadedmetadata = () => {
            video.play().then(() => setReady(true)).catch(() => setError(cameraErrorMessage({ name: 'AbortError' })));
          };
        }
      })
      .catch((err) => {
        if (!cancelled) setError(cameraErrorMessage(err));
      });
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video || !ready || busy || atLimit) return;
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) {
      setError('The camera did not deliver a picture. Please try again.');
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      setError('This device could not save the photo. Use "Choose photos" instead.');
      return;
    }
    setBusy(true);
    ctx.drawImage(video, 0, 0, w, h);
    canvas.toBlob(
      (blob) => {
        setBusy(false);
        if (!blob || blob.size === 0) {
          setError('Saving the photo failed. Please try again.');
          return;
        }
        setFlash(true);
        window.setTimeout(() => setFlash(false), 180);
        onCapture(blob);
      },
      'image/jpeg',
      0.93,
    );
  }, [ready, busy, atLimit, onCapture]);

  return (
    <div
      className="fixed inset-0 z-[80] bg-[#0A241D] flex flex-col"
      role="dialog"
      aria-modal="true"
      aria-label="Invoice camera"
    >
      <div className="flex items-center justify-between px-4 py-3 text-white">
        <button
          type="button"
          onClick={onClose}
          className="inline-flex items-center gap-2 min-h-12 px-4 rounded-xl bg-white/10 hover:bg-white/20 text-sm font-semibold cursor-pointer"
        >
          <X className="w-5 h-5" aria-hidden="true" />
          Close
        </button>
        <p className="text-sm font-semibold" aria-live="polite">
          {pagesSoFar === 0 ? 'Page 1' : `${pagesSoFar} page${pagesSoFar > 1 ? 's' : ''} captured`}
        </p>
        <button
          type="button"
          onClick={onClose}
          disabled={pagesSoFar === 0}
          className="inline-flex items-center gap-2 min-h-12 px-4 rounded-xl bg-[#D6AE62] text-[#153D32] text-sm font-bold disabled:opacity-40 cursor-pointer"
        >
          <Check className="w-5 h-5" aria-hidden="true" />
          Done
        </button>
      </div>

      <div className="relative flex-1 min-h-0 flex items-center justify-center overflow-hidden">
        {error ? (
          <div className="max-w-sm mx-4 bg-white rounded-2xl p-6 text-center">
            <AlertTriangle className="w-8 h-8 text-[#EF806D] mx-auto mb-3" aria-hidden="true" />
            <p className="text-sm text-[#252D29] mb-5">{error}</p>
            <button
              type="button"
              onClick={() => {
                onClose();
                onFallback();
              }}
              className="w-full inline-flex items-center justify-center gap-2 min-h-12 rounded-xl bg-[#153D32] text-white text-sm font-bold cursor-pointer"
            >
              <ImagePlus className="w-5 h-5" aria-hidden="true" />
              Take or choose photos instead
            </button>
          </div>
        ) : (
          <>
            <video ref={videoRef} playsInline muted className="max-h-full max-w-full object-contain" />
            {/* Framing guide: keep the whole invoice inside */}
            <div className="pointer-events-none absolute inset-6 sm:inset-10 border-2 border-dashed border-white/60 rounded-xl" />
            {!ready && <p className="absolute text-white/80 text-sm">Starting camera…</p>}
            {flash && <div className="absolute inset-0 bg-white/70" />}
          </>
        )}
      </div>

      {!error && (
        <div className="px-4 pt-3 pb-6 flex flex-col items-center gap-2 text-white">
          <p className="text-xs text-white/80 text-center">
            {atLimit
              ? `Maximum of ${maxPages} pages reached.`
              : 'Fit the whole page inside the frame, hold steady, and use good light.'}
          </p>
          <button
            type="button"
            onClick={capture}
            disabled={!ready || busy || atLimit}
            aria-label="Capture page"
            className="w-20 h-20 rounded-full bg-white border-[6px] border-[#23866A] flex items-center justify-center disabled:opacity-40 cursor-pointer active:scale-95 transition-transform"
          >
            <Camera className="w-8 h-8 text-[#153D32]" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
};
