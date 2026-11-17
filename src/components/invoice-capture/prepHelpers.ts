/**
 * Pure helpers for the invoice capture & preparation workflow (unit-tested, no React).
 */
import type { PreparedPage, QualityGrade, Rotation } from '../../api/documentPrep';

export const WORKFLOW_STEPS = [
  'Capture or upload',
  'Quality check',
  'Automatic rotation',
  'Enhancement',
  'Preview & correct',
  'Prepare PDF',
  'Read invoice (OCR)',
  'Results',
] as const;

export type WorkflowPhase = 'capture' | 'processing' | 'review' | 'pdf' | 'ocr' | 'done';

/** Zero-based index of the highlighted workflow step. */
export function workflowStepIndex(phase: WorkflowPhase, processingStage = 0): number {
  switch (phase) {
    case 'capture':
      return 0;
    case 'processing':
      return 1 + Math.max(0, Math.min(2, processingStage));
    case 'review':
      return 4;
    case 'pdf':
      return 5;
    case 'ocr':
      return 6;
    case 'done':
      return 7;
  }
}

export interface GradeInfo {
  label: string;
  tone: 'good' | 'ok' | 'warn' | 'bad';
  badgeClass: string;
}

const GRADE_INFO: Record<QualityGrade, GradeInfo> = {
  EXCELLENT: { label: 'Excellent', tone: 'good', badgeClass: 'bg-[#E7F6F1] text-[#16704F] border-[#23866A]/30' },
  GOOD: { label: 'Good', tone: 'good', badgeClass: 'bg-[#E7F6F1] text-[#16704F] border-[#23866A]/30' },
  NEEDS_ENHANCEMENT: { label: 'Needs fixing', tone: 'ok', badgeClass: 'bg-[#FBF4E7] text-[#8A6420] border-[#D6AE62]/50' },
  POOR: { label: 'Poor', tone: 'warn', badgeClass: 'bg-[#FDF1EF] text-[#B4483A] border-[#EF806D]/40' },
  UNREADABLE: { label: 'Unreadable', tone: 'bad', badgeClass: 'bg-[#FDF1EF] text-[#B4483A] border-[#EF806D]/60' },
};

export function gradeInfo(grade: QualityGrade | string | undefined | null): GradeInfo {
  return GRADE_INFO[(grade as QualityGrade) ?? 'GOOD'] ?? {
    label: 'Unknown',
    tone: 'ok',
    badgeClass: 'bg-[#FAF8F2] text-[#5E6C64] border-[#DDE9DF]',
  };
}

export function normalizeRotation(deg: number): Rotation {
  const r = (((Math.round(deg / 90) * 90) % 360) + 360) % 360;
  return r as Rotation;
}

/** Return a copy of `items` with the element at `from` moved to `to` (clamped). */
export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  const next = items.slice();
  if (from < 0 || from >= next.length) return next;
  const target = Math.max(0, Math.min(next.length - 1, to));
  const [item] = next.splice(from, 1);
  next.splice(target, 0, item);
  return next;
}

export function rotationLabel(deg: number): string {
  switch (normalizeRotation(deg)) {
    case 90:
      return 'turned right (90°)';
    case 180:
      return 'turned upside down (180°)';
    case 270:
      return 'turned left (90°)';
    default:
      return 'not turned';
  }
}

/** Plain-language list of what was done to a page, for shop owners. */
export function describeCorrections(page: PreparedPage): string[] {
  const out: string[] = [];
  const auto = normalizeRotation(page.auto_rotation_cw || 0);
  if (auto !== 0) {
    const conf = Math.round((page.orientation?.confidence ?? 0) * 100);
    out.push(`Page was ${rotationLabel(auto)} automatically (${conf}% sure).`);
  } else {
    out.push('Page was already upright.');
  }
  if (page.orientation?.deskew_applied) {
    out.push(`Straightened a ${Math.abs(page.orientation.skew_deg).toFixed(1)}° tilt.`);
  }
  if (page.document?.perspective_corrected) {
    out.push('Corrected the camera angle and removed the background.');
  }
  const enh = page.enhancement?.steps?.filter((s) => s.name !== 'grayscale') ?? [];
  const names: Record<string, string> = {
    illumination_correction: 'evened out shadows and lighting',
    denoise: 'reduced grain',
    upscale: 'enlarged small text',
    contrast_stretch: 'improved contrast',
    clahe: 'boosted very faint print',
    selective_sharpen: 'gently sharpened text',
  };
  if (enh.length) {
    out.push(`Enhanced: ${enh.map((s) => names[s.name] ?? s.name).join(', ')}.`);
  } else if (page.enhancement?.rejected_reason) {
    out.push('Enhancement skipped to protect small text.');
  }
  const manual = normalizeRotation(page.manual_rotation || 0);
  if (manual !== 0) {
    const how = { 90: 'right (90°)', 180: 'upside down (180°)', 270: 'left (90°)' }[manual];
    out.push(`You turned the page ${how}.`);
  }
  return out;
}

/** Message for a getUserMedia failure, in words a shop owner can act on. */
export function cameraErrorMessage(err: unknown): string {
  const name = (err as { name?: string })?.name ?? '';
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return 'Camera permission was denied. Allow camera access in your browser or phone settings, or use "Choose photos" instead.';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return 'No camera was found on this device. Use "Choose photos" to upload pictures instead.';
    case 'NotReadableError':
    case 'TrackStartError':
    case 'AbortError':
      return 'The camera is busy or could not start. Close other apps using the camera and try again.';
    case 'InsecureContext':
    case 'Unsupported':
    case 'NotSupportedError':
      return 'The live camera is not available here. Use "Take photo" or "Choose photos" instead.';
    default:
      return 'The camera could not be opened. Use "Choose photos" to upload pictures instead.';
  }
}

export function canUseLiveCamera(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === 'function' &&
    (typeof window === 'undefined' || window.isSecureContext !== false)
  );
}

/**
 * Detected page outline as SVG polygon points in a viewBox of the displayed preview, taking
 * the manual rotation (clockwise) applied to the preview into account.
 */
export function outlinePoints(
  quad: number[][] | null | undefined,
  imageSize: [number, number] | null | undefined,
  rotation: number,
): { points: string; viewBox: string } | null {
  if (!quad || quad.length !== 4 || !imageSize) return null;
  let [w, h] = imageSize;
  let pts = quad.map(([x, y]) => [x, y]);
  const turns = normalizeRotation(rotation) / 90;
  for (let i = 0; i < turns; i++) {
    // 90° clockwise: (x, y) -> (h - y, x) and the frame becomes h x w
    pts = pts.map(([x, y]) => [h - y, x]);
    [w, h] = [h, w];
  }
  return {
    points: pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '),
    viewBox: `0 0 ${w} ${h}`,
  };
}

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/heic', 'image/heif', 'image/webp', 'image/bmp', 'image/tiff'];
const ACCEPTED_EXT = /\.(jpe?g|png|heic|heif|webp|bmp|tiff?)$/i;

/** Client-side pre-check; the server re-validates the actual file content. */
export function validatePhotoFile(file: { name: string; type: string; size: number }, maxMb = 25): string | null {
  if (!ACCEPTED_TYPES.includes(file.type) && !ACCEPTED_EXT.test(file.name)) {
    if (/\.pdf$/i.test(file.name) || file.type === 'application/pdf') {
      return `"${file.name}" is a PDF. Use "Upload PDF or file" for PDFs; this scanner is for photos.`;
    }
    return `"${file.name}" is not a photo. Please choose JPG, PNG, HEIC, WEBP, BMP or TIFF images.`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > maxMb * 1024 * 1024) return `"${file.name}" is larger than ${maxMb} MB.`;
  return null;
}
