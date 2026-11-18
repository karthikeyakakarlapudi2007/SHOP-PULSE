/**
 * @file documentPrep.ts
 * @description Client for the invoice photo preparation API (/api/v1/document-prep).
 * Capture -> automatic correction -> manual review -> PDF -> existing OCR extraction.
 */
import { apiClient, getAccessToken, uploadWithProgress, ApiError, type UploadOptions } from './client';

const BASE = '/api/v1/document-prep';

export type QualityGrade = 'EXCELLENT' | 'GOOD' | 'NEEDS_ENHANCEMENT' | 'POOR' | 'UNREADABLE';
export type VariantName = 'original' | 'corrected' | 'enhanced' | 'binarized';
export type Rotation = 0 | 90 | 180 | 270;

export interface QualityIssue {
  code: string;
  severity: number;
  message: string;
  correctable: boolean;
}

export interface QualityReport {
  grade: QualityGrade;
  score: number;
  retake_recommended: boolean;
  summary: string;
  metrics: Record<string, number>;
  issues: QualityIssue[];
}

export interface PrepStep {
  step: string;
  applied: boolean;
  reason: string;
  details?: Record<string, unknown>;
}

export interface PreparedPage {
  page_id: string;
  index: number;
  filename: string | null;
  variants: { name: VariantName; label: string }[];
  recommended_variant: VariantName;
  selected_variant: VariantName;
  manual_rotation: Rotation;
  auto_rotation_cw: number;
  orientation: {
    auto_rotation_cw: number;
    detected_rotation_cw: number;
    confidence: number;
    method: string;
    skew_deg: number;
    deskew_applied: boolean;
    needs_confirmation: boolean;
    notes: string[];
  };
  document: {
    found: boolean;
    perspective_corrected: boolean;
    quad: number[][] | null;
    reasons: string[];
    image_size: [number, number] | null;
  };
  quality_before: QualityReport;
  quality_after: QualityReport;
  enhancement: {
    applied: boolean;
    steps?: { name: string; reason: string; params: Record<string, number> }[];
    reason?: string;
    rejected_reason?: string;
  };
  selection: { method: string; chosen: string; reason?: string; scores?: Record<string, { score: number }> };
  steps: PrepStep[];
  warnings: string[];
  retake_recommended: boolean;
  needs_confirmation: boolean;
  needs_user_choice: boolean;
  timings_ms: Record<string, number>;
  image_url: string;
  original_url: string;
}

export interface PrepSession {
  session_id: string;
  pages: PreparedPage[];
  page_count: number;
  limits: { max_pages: number; max_upload_mb: number; accepted_types: string[] };
}

export type DocumentSource = 'processed' | 'original';

export interface PrepExtractResult {
  extraction: any;
  preparation: {
    session_id: string;
    source: DocumentSource;
    document_name: string;
    page_count: number;
    pages: { page_id: string; variant: string; manual_rotation: number; quality_before?: string; quality_after?: string }[];
    archived: boolean;
  };
}

/** Photo-quality check for a directly uploaded photo (no preparation, no OCR). */
export interface PhotoAssessment {
  filename?: string | null;
  quality: QualityReport;
  retake_recommended: boolean;
  document: {
    found: boolean;
    outline_reliable: boolean;
    cut_off: boolean;
    cut_off_edges: string[];
    reasons: string[];
  };
}

export const documentPrepApi = {
  /** Grade a photo that is sent straight to OCR, so poor or cut-off photos are reported (R10). */
  assess: (file: Blob, filename: string) => {
    const form = new FormData();
    form.append('file', file, filename);
    return uploadWithProgress<PhotoAssessment>(`${BASE}/assess`, form);
  },
  createSession: () => apiClient.post<PrepSession>(`${BASE}/sessions`),
  getSession: (sessionId: string) => apiClient.get<PrepSession>(`${BASE}/sessions/${sessionId}`),
  deleteSession: (sessionId: string) => apiClient.delete<void>(`${BASE}/sessions/${sessionId}`),

  addPage: (sessionId: string, file: Blob, filename: string, options: UploadOptions = {}) => {
    const form = new FormData();
    form.append('file', file, filename);
    return uploadWithProgress<PreparedPage>(`${BASE}/sessions/${sessionId}/pages`, form, options);
  },
  reprocessPage: (
    sessionId: string,
    pageId: string,
    options: { auto_orientation?: boolean; perspective?: boolean; deskew?: boolean; enhance?: boolean },
  ) => apiClient.post<PreparedPage>(`${BASE}/sessions/${sessionId}/pages/${pageId}/reprocess`, options),
  updatePage: (
    sessionId: string,
    pageId: string,
    update: { rotation?: Rotation; rotate_by?: -90 | 90 | 180 | 270; selected_variant?: VariantName },
  ) => apiClient.patch<PreparedPage>(`${BASE}/sessions/${sessionId}/pages/${pageId}`, update),
  deletePage: (sessionId: string, pageId: string) =>
    apiClient.delete<PrepSession>(`${BASE}/sessions/${sessionId}/pages/${pageId}`),
  reorder: (sessionId: string, pageIds: string[]) =>
    apiClient.put<PrepSession>(`${BASE}/sessions/${sessionId}/order`, { page_ids: pageIds }),
  extract: (sessionId: string, source: DocumentSource = 'processed') =>
    apiClient.post<PrepExtractResult>(`${BASE}/sessions/${sessionId}/extract`, { source }),

  /** Download the PDF that will be (or was) sent to OCR. */
  downloadPdf: async (sessionId: string, source: DocumentSource = 'processed'): Promise<Blob> => {
    return fetchBlob(`${BASE}/sessions/${sessionId}/pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source }),
    });
  },
};

/** Authenticated binary fetch (images are private, so <img src> cannot carry the token). */
export async function fetchBlob(url: string, init: RequestInit = {}): Promise<Blob> {
  const token = getAccessToken();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers });
  } catch (err: any) {
    throw new ApiError('Unable to reach the server. Check your connection and try again.', 0, err, 'NETWORK_ERROR');
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      // not JSON
    }
    throw new ApiError(detail, res.status);
  }
  return res.blob();
}

export function pageImageUrl(
  page: Pick<PreparedPage, 'image_url'>,
  variant: VariantName,
  size: 'thumb' | 'preview' | 'full' = 'preview',
): string {
  return `${page.image_url}?variant=${variant}&size=${size}`;
}
