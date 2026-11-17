/**
 * Invoice capture & preparation workflow: pure helpers (rotation math, page reordering,
 * outline overlay geometry, quality labels, camera error messages, photo validation) and the
 * API client's request shapes.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import {
  WORKFLOW_STEPS,
  cameraErrorMessage,
  describeCorrections,
  gradeInfo,
  moveItem,
  normalizeRotation,
  outlinePoints,
  validatePhotoFile,
  workflowStepIndex,
} from '../components/invoice-capture/prepHelpers';
import { documentPrepApi, pageImageUrl, type PreparedPage } from '../api/documentPrep';

afterEach(() => vi.unstubAllGlobals());

describe('workflow steps', () => {
  it('lists the eight stages in order', () => {
    expect(WORKFLOW_STEPS).toHaveLength(8);
    expect(WORKFLOW_STEPS[0]).toMatch(/Capture/);
    expect(WORKFLOW_STEPS[7]).toBe('Results');
  });
  it('maps phases to the highlighted step', () => {
    expect(workflowStepIndex('capture')).toBe(0);
    expect(workflowStepIndex('processing')).toBe(1);
    expect(workflowStepIndex('review')).toBe(4);
    expect(workflowStepIndex('pdf')).toBe(5);
    expect(workflowStepIndex('ocr')).toBe(6);
    expect(workflowStepIndex('done')).toBe(7);
  });
});

describe('rotation and ordering', () => {
  it('normalises any multiple of 90 into 0..270', () => {
    expect(normalizeRotation(-90)).toBe(270);
    expect(normalizeRotation(450)).toBe(90);
    expect(normalizeRotation(360)).toBe(0);
    expect(normalizeRotation(180)).toBe(180);
  });
  it('moves pages without losing any', () => {
    expect(moveItem(['a', 'b', 'c'], 2, 0)).toEqual(['c', 'a', 'b']);
    expect(moveItem(['a', 'b', 'c'], 0, 5)).toEqual(['b', 'c', 'a']);
    expect(moveItem(['a', 'b', 'c'], 9, 0)).toEqual(['a', 'b', 'c']);
  });
});

describe('page outline overlay', () => {
  const quad = [[10, 20], [90, 20], [90, 180], [10, 180]];
  it('uses the image frame when not rotated', () => {
    expect(outlinePoints(quad, [100, 200], 0)).toEqual({
      points: '10.0,20.0 90.0,20.0 90.0,180.0 10.0,180.0',
      viewBox: '0 0 100 200',
    });
  });
  it('follows a clockwise manual rotation', () => {
    const r = outlinePoints([[10, 20], [0, 0], [0, 0], [0, 0]], [100, 200], 90)!;
    expect(r.viewBox).toBe('0 0 200 100');
    expect(r.points.startsWith('180.0,10.0')).toBe(true); // (x,y) -> (h - y, x)
  });
  it('returns nothing without a detected outline', () => {
    expect(outlinePoints(null, [100, 200], 0)).toBeNull();
  });
});

describe('quality labels and messages', () => {
  it('labels every grade in plain words', () => {
    expect(gradeInfo('EXCELLENT').label).toBe('Excellent');
    expect(gradeInfo('NEEDS_ENHANCEMENT').label).toBe('Needs fixing');
    expect(gradeInfo('UNREADABLE').tone).toBe('bad');
    expect(gradeInfo('SOMETHING_ELSE').label).toBe('Unknown');
  });
  it('explains camera failures with an alternative', () => {
    expect(cameraErrorMessage({ name: 'NotAllowedError' })).toMatch(/permission/i);
    expect(cameraErrorMessage({ name: 'NotFoundError' })).toMatch(/No camera/);
    expect(cameraErrorMessage({ name: 'NotReadableError' })).toMatch(/busy/);
    expect(cameraErrorMessage(new Error('x'))).toMatch(/Choose photos/);
  });
  it('validates photos before upload', () => {
    expect(validatePhotoFile({ name: 'a.jpg', type: 'image/jpeg', size: 1000 })).toBeNull();
    expect(validatePhotoFile({ name: 'a.heic', type: 'image/heic', size: 1000 })).toMatch(/HEIC/);
    expect(validatePhotoFile({ name: 'a.pdf', type: 'application/pdf', size: 1000 })).toMatch(/PDF/);
    expect(validatePhotoFile({ name: 'a.jpg', type: 'image/jpeg', size: 0 })).toMatch(/empty/);
    expect(validatePhotoFile({ name: 'a.jpg', type: 'image/jpeg', size: 30 * 1024 * 1024 })).toMatch(/25 MB/);
    expect(validatePhotoFile({ name: 'a.exe', type: 'application/octet-stream', size: 10 })).toMatch(/not a photo/);
  });
});

describe('describeCorrections', () => {
  const page = {
    auto_rotation_cw: 180,
    manual_rotation: 90,
    orientation: { confidence: 0.92, deskew_applied: true, skew_deg: -3.96 },
    document: { perspective_corrected: true },
    enhancement: { applied: true, steps: [{ name: 'grayscale' }, { name: 'illumination_correction' }, { name: 'upscale' }] },
  } as unknown as PreparedPage;
  it('describes every applied correction for the shop owner', () => {
    const lines = describeCorrections(page);
    expect(lines[0]).toBe('Page was turned upside down (180°) automatically (92% sure).');
    expect(lines).toContain('Straightened a 4.0° tilt.');
    expect(lines).toContain('Corrected the camera angle and removed the background.');
    expect(lines).toContain('Enhanced: evened out shadows and lighting, enlarged small text.');
    expect(lines).toContain('You turned the page right (90°).');
  });
});

describe('documentPrepApi', () => {
  it('sends manual rotation and version choice as PATCH JSON', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ page_id: 'p' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await documentPrepApi.updatePage('s1', 'p1', { rotate_by: -90 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/api\/v1\/document-prep\/sessions\/s1\/pages\/p1$/);
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({ rotate_by: -90 });
  });
  it('requests extraction of processed or original pages', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ extraction: {}, preparation: {} }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await documentPrepApi.extract('s1', 'original');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/sessions\/s1\/extract$/);
    expect(JSON.parse(String(init.body))).toEqual({ source: 'original' });
  });
  it('builds image URLs for a version and size', () => {
    expect(pageImageUrl({ image_url: '/x/image' }, 'enhanced', 'thumb')).toBe('/x/image?variant=enhanced&size=thumb');
  });
});
