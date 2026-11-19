"""
Document boundary detection and perspective correction.

Candidate outlines come from three independent detectors (edges, brightness segmentation and
colour distance from the background seen at the photo border), so a page on a table that is
almost the same colour as the paper still has a chance of being found.  Each candidate is
then *validated*, not trusted:

* geometry: convex quadrilateral, sensible corner angles, plausible area;
* evidence: the outline must sit on real image edges (sides lying on the photo border are
  allowed - the page was only partly in frame);
* content safety: practically no text may lie outside the outline, so correcting the
  perspective can never crop invoice content.

When no candidate passes, the original framing is kept rather than applying a doubtful warp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.document_prep.analysis import TextAnalysis, analyze_text, resize_max_side, to_gray
from services.document_prep.config import DocumentPrepConfig, default_config

DETECT_MAX_SIDE = 1000


@dataclass
class DocumentDetection:
    found: bool
    should_warp: bool
    quad: Optional[List[List[float]]]  # tl, tr, br, bl in input-image pixel coordinates
    method: Optional[str]
    confidence: float
    area_fraction: float
    touches_border: bool
    max_corner_deviation_deg: float  # how far corners are from 90 degrees (perspective strength)
    text_outside_fraction: float
    output_size: Optional[Tuple[int, int]] = None
    aspect_ratio: Optional[float] = None
    aspect_method: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    candidates_considered: int = 0
    # R8: an outline with 1-3 corners on the photo frame is bounded by the frame, not by the paper,
    # so it is not used for reshaping; with text running into that frame edge the page is cut off.
    outline_reliable: bool = True
    corners_on_frame: int = 0
    cut_off: bool = False
    cut_off_edges: List[str] = field(default_factory=list)


def order_corners(pts: np.ndarray) -> np.ndarray:
    """Return tl, tr, br, bl as they appear in the image."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    pts = pts[np.argsort(ang)]  # clockwise in image coords, starting near -180 deg (left)
    # rotate so that the first point is the one with the smallest x + y (top-left)
    start = int(np.argmin(pts.sum(axis=1)))
    pts = np.roll(pts, -start, axis=0)
    return pts


def _corner_angles(q: np.ndarray) -> np.ndarray:
    angs = []
    for i in range(4):
        p0, p1, p2 = q[i - 1], q[i], q[(i + 1) % 4]
        v1, v2 = p0 - p1, p2 - p1
        cosv = np.dot(v1, v2) / max(1e-6, np.linalg.norm(v1) * np.linalg.norm(v2))
        angs.append(np.degrees(np.arccos(np.clip(cosv, -1, 1))))
    return np.array(angs)


def _quad_from_contour(cnt: np.ndarray) -> Optional[np.ndarray]:
    hull = cv2.convexHull(cnt)
    peri = cv2.arcLength(hull, True)
    for eps in (0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.07):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype(np.float32)
        if len(approx) < 4:
            break
    if len(hull) >= 4:
        # Fallback: the four hull points extreme along the diagonals (works for 5-6 point hulls)
        pts = hull.reshape(-1, 2).astype(np.float32)
        s = pts.sum(1)
        d = pts[:, 1] - pts[:, 0]
        quad = np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]])
        if len({tuple(p) for p in quad.tolist()}) == 4:
            return quad
    return None


def _line_intersection(l1, l2) -> Optional[np.ndarray]:
    (x1, y1), (x2, y2) = l1
    (x3, y3), (x4, y4) = l2
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return np.array([(a * (x3 - x4) - (x1 - x2) * b) / den, (a * (y3 - y4) - (y1 - y2) * b) / den], np.float32)


def _quad_from_longest_sides(cnt: np.ndarray) -> Optional[np.ndarray]:
    """Fit the outline with its four longest straight runs and intersect them.

    Robust to a blob of clutter fused to one corner of the page outline, where the convex
    hull (and therefore approxPolyDP on it) would cut the corner off.
    """
    peri = cv2.arcLength(cnt, True)
    approx = cv2.approxPolyDP(cnt, 0.006 * peri, True).reshape(-1, 2).astype(np.float32)
    if len(approx) < 4:
        return None
    segs = [(approx[i], approx[(i + 1) % len(approx)]) for i in range(len(approx))]
    lengths = np.array([np.linalg.norm(b - a) for a, b in segs])
    order = np.argsort(-lengths)
    chosen: List[int] = []
    for i in order:
        a, b = segs[i]
        ang = np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0])) % 180
        dup = False
        for j in chosen:
            c, d = segs[j]
            ang2 = np.degrees(np.arctan2(d[1] - c[1], d[0] - c[0])) % 180
            diff = abs(ang - ang2)
            diff = min(diff, 180 - diff)
            mid1, mid2 = (a + b) / 2, (c + d) / 2
            if diff < 20 and np.linalg.norm(mid1 - mid2) < 0.15 * peri / 4:
                dup = True  # same side split into two runs
                break
        if not dup:
            chosen.append(int(i))
        if len(chosen) == 4:
            break
    if len(chosen) < 4 or lengths[chosen].sum() < 0.6 * peri:
        return None
    centre = approx.mean(axis=0)
    mids = [((segs[i][0] + segs[i][1]) / 2) for i in chosen]
    angles = [np.arctan2(m[1] - centre[1], m[0] - centre[0]) for m in mids]
    chosen = [chosen[k] for k in np.argsort(angles)]
    corners = []
    for k in range(4):
        p = _line_intersection(segs[chosen[k]], segs[chosen[(k + 1) % 4]])
        if p is None:
            return None
        corners.append(p)
    return np.array(corners, np.float32)


def _largest_component_quads(binary: np.ndarray, top: int = 3) -> List[np.ndarray]:
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:top]
    quads = []
    for c in contours:
        if cv2.contourArea(c) < 0.05 * binary.shape[0] * binary.shape[1]:
            continue
        for fit in (_quad_from_contour, _quad_from_longest_sides):
            q = fit(c)
            if q is not None:
                quads.append(q)
    return quads


def _candidates(small_bgr: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    h, w = small_bgr.shape[:2]
    gray = to_gray(small_bgr)
    out: List[Tuple[str, np.ndarray]] = []
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, w // 60) | 1, max(5, h // 60) | 1))

    # 1. Edges
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    med = float(np.median(blur))
    lo, hi = int(max(10, 0.5 * med)), int(min(255, max(40, 1.2 * med)))
    edges = cv2.Canny(blur, lo // 2, hi // 2)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    edges_closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, close_k)
    # 1a. Closed outline loops: a page edge seen against any background is a closed loop of
    #     edges; its inner contour is the page, independent of clutter outside it.
    loops, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    loops = [c for c in loops if cv2.contourArea(c) >= 0.15 * h * w]
    for c in sorted(loops, key=cv2.contourArea, reverse=True)[:4]:
        q = _quad_from_contour(c)
        if q is not None:
            out.append(("edge_loop", q))
    # 1b. Filled edge region, opened to cut off clutter fused to the outline
    filled = np.zeros_like(edges)
    cnts, _ = cv2.findContours(edges_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, cnts, -1, 255, thickness=cv2.FILLED)
    open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 25) | 1, max(9, h // 25) | 1))
    filled = cv2.morphologyEx(filled, cv2.MORPH_OPEN, open_k)
    out += [("edges", q) for q in _largest_component_quads(filled)]

    # 2. Brightness (paper is usually the brightest large region)
    _, bright = cv2.threshold(cv2.GaussianBlur(gray, (9, 9), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, close_k, iterations=2)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    out += [("brightness", q) for q in _largest_component_quads(bright)]

    # 3. Colour distance from the background seen along the photo border
    lab = cv2.cvtColor(cv2.GaussianBlur(small_bgr, (7, 7), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    bw = max(3, min(h, w) // 40)
    border = np.concatenate([lab[:bw].reshape(-1, 3), lab[-bw:].reshape(-1, 3),
                             lab[:, :bw].reshape(-1, 3), lab[:, -bw:].reshape(-1, 3)])
    bg_col = np.median(border, axis=0)
    dist = np.sqrt(((lab - bg_col) ** 2).sum(-1))
    dist8 = np.clip(dist * (255.0 / max(1.0, np.percentile(dist, 99))), 0, 255).astype(np.uint8)
    _, fg = cv2.threshold(dist8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, close_k, iterations=2)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7)))
    out += [("color_distance", q) for q in _largest_component_quads(fg)]
    return out


def _side_support(grad: np.ndarray, quad: np.ndarray, border_tol: float) -> Tuple[float, int]:
    """Mean fraction of points along non-border sides that sit on a strong gradient."""
    h, w = grad.shape[:2]
    strong = grad > max(8.0, np.percentile(grad, 80))
    strong = cv2.dilate(strong.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    supports = []
    border_sides = 0
    for i in range(4):
        p, q = quad[i], quad[(i + 1) % 4]
        on_border = (
            (p[0] <= border_tol and q[0] <= border_tol) or (p[1] <= border_tol and q[1] <= border_tol)
            or (p[0] >= w - 1 - border_tol and q[0] >= w - 1 - border_tol)
            or (p[1] >= h - 1 - border_tol and q[1] >= h - 1 - border_tol)
        )
        if on_border:
            border_sides += 1
            continue
        n = max(20, int(np.linalg.norm(q - p) / 3))
        t = np.linspace(0.05, 0.95, n)
        xs = np.clip((p[0] + (q[0] - p[0]) * t).astype(int), 0, w - 1)
        ys = np.clip((p[1] + (q[1] - p[1]) * t).astype(int), 0, h - 1)
        supports.append(float(strong[ys, xs].mean()))
    if not supports:
        return 0.0, border_sides
    return float(np.mean(supports)) if border_sides == 0 else float(np.min(supports)), border_sides


def estimate_aspect_ratio(quad: np.ndarray, image_size: Tuple[int, int]) -> Tuple[float, str]:
    """Width/height of the real rectangle seen through perspective (Zhang & He, 2007).

    Falls back to the mean of opposite side lengths when the focal length cannot be
    recovered (near-fronto-parallel views or degenerate geometry).
    """
    tl, tr, br, bl = [np.array([p[0], p[1], 1.0]) for p in quad]
    w_img, h_img = image_size
    u0, v0 = w_img / 2.0, h_img / 2.0
    top = np.linalg.norm(tr[:2] - tl[:2])
    bottom = np.linalg.norm(br[:2] - bl[:2])
    left = np.linalg.norm(bl[:2] - tl[:2])
    right = np.linalg.norm(br[:2] - tr[:2])
    simple = ((top + bottom) / 2.0) / max(1e-6, (left + right) / 2.0)
    m1, m2, m3, m4 = tl, tr, bl, br
    try:
        k2 = np.dot(np.cross(m1, m4), m3) / np.dot(np.cross(m2, m4), m3)
        k3 = np.dot(np.cross(m1, m4), m2) / np.dot(np.cross(m3, m4), m2)
        n2 = k2 * m2 - m1
        n3 = k3 * m3 - m1
        if abs(n2[2]) < 1e-6 or abs(n3[2]) < 1e-6:
            return simple, "side_lengths"
        f2 = -(
            (n2[0] * n3[0] - (n2[0] * n3[2] + n2[2] * n3[0]) * u0 + n2[2] * n3[2] * u0 * u0)
            + (n2[1] * n3[1] - (n2[1] * n3[2] + n2[2] * n3[1]) * v0 + n2[2] * n3[2] * v0 * v0)
        ) / (n2[2] * n3[2])
        if not np.isfinite(f2) or f2 <= 0:
            return simple, "side_lengths"
        f = np.sqrt(f2)
        a = np.array([[f, 0, u0], [0, f, v0], [0, 0, 1]], dtype=np.float64)
        ai = np.linalg.inv(a)
        b = ai.T @ ai
        r2 = (n2 @ b @ n2) / (n3 @ b @ n3)
        if not np.isfinite(r2) or r2 <= 0:
            return simple, "side_lengths"
        ratio = float(np.sqrt(r2))
        # Guard against unstable estimates: stay within 25% of the naive ratio
        if not (0.75 * simple <= ratio <= 1.25 * simple):
            return simple, "side_lengths"
        return ratio, "projective"
    except (FloatingPointError, np.linalg.LinAlgError, ZeroDivisionError):
        return simple, "side_lengths"


def detect_document(
    img: np.ndarray,
    analysis: Optional[TextAnalysis] = None,
    config: DocumentPrepConfig = default_config,
) -> DocumentDetection:
    h, w = img.shape[:2]
    small, scale = resize_max_side(img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), DETECT_MAX_SIDE)
    sh, sw = small.shape[:2]
    gray = to_gray(small)
    gx = cv2.Sobel(cv2.GaussianBlur(gray, (5, 5), 0), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(cv2.GaussianBlur(gray, (5, 5), 0), cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy)

    a = analysis or analyze_text(img)
    # Text pixels at the detection scale (from the full analysis mask)
    text_small = cv2.resize(a.text_mask, (sw, sh), interpolation=cv2.INTER_NEAREST) if a.n_chars else None
    text_total = float(np.count_nonzero(text_small)) if text_small is not None else 0.0

    cands = _candidates(small)
    border_tol = max(3.0, 0.012 * max(sw, sh))
    best = None
    rejected: Dict[str, int] = {}
    lab_small = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    ring_w = max(4, int(0.02 * max(sw, sh)))
    for method, quad in cands:
        q = order_corners(quad)
        area = abs(cv2.contourArea(q)) / float(sw * sh)
        if area < config.min_document_area_fraction:
            rejected["too_small"] = rejected.get("too_small", 0) + 1
            continue
        if not cv2.isContourConvex(q.astype(np.int32).reshape(-1, 1, 2)):
            rejected["not_convex"] = rejected.get("not_convex", 0) + 1
            continue
        angs = _corner_angles(q)
        if angs.min() < 50 or angs.max() > 130:
            rejected["bad_angles"] = rejected.get("bad_angles", 0) + 1
            continue
        support, border_sides = _side_support(grad, q, border_tol)
        if border_sides >= 3:
            rejected["mostly_frame"] = rejected.get("mostly_frame", 0) + 1
            continue
        region = np.zeros((sh, sw), np.uint8)
        cv2.fillConvexPoly(region, q.astype(np.int32), 255)
        # Boundary contrast: just outside a real page edge there is table / background, not
        # more paper.  A table border or text block inside the page has paper on both sides.
        inner = cv2.erode(region, np.ones((ring_w * 3, ring_w * 3), np.uint8))
        paper_px = lab_small[inner > 0] if np.count_nonzero(inner) > 100 else lab_small[region > 0]
        # Paper level ignores ink: bright percentile of lightness, median chroma
        paper = np.array([np.percentile(paper_px[:, 0], 85), np.median(paper_px[:, 1]), np.median(paper_px[:, 2])])
        # Band from 1x to 5x ring width outside the outline: skips blur/shadow right at the edge
        outer_ring = cv2.bitwise_and(
            cv2.dilate(region, np.ones((ring_w * 10 + 1, ring_w * 10 + 1), np.uint8)),
            cv2.bitwise_not(cv2.dilate(region, np.ones((ring_w * 2 + 1, ring_w * 2 + 1), np.uint8))))
        ring_px = lab_small[outer_ring > 0]
        if ring_px.size == 0:
            paper_like = 0.0
        else:
            de = np.sqrt(((ring_px - paper) ** 2).sum(-1))
            paper_like = float((de < 10.0).mean())
        if paper_like > 0.45:
            rejected["paper_outside"] = rejected.get("paper_outside", 0) + 1
            continue
        # Content safety: text-like marks lying on paper-coloured pixels outside the outline
        outside = 0.0
        if text_total > 0:
            paper_mask = (np.sqrt(((lab_small - paper) ** 2).sum(-1)) < 18.0).astype(np.uint8) * 255
            paper_mask = cv2.dilate(paper_mask, np.ones((5, 5), np.uint8))
            reg_d = cv2.dilate(region, np.ones((7, 7), np.uint8))
            outside_text = cv2.bitwise_and(cv2.bitwise_and(text_small, cv2.bitwise_not(reg_d)), paper_mask)
            inside_text = float(np.count_nonzero(cv2.bitwise_and(text_small, reg_d))) or 1.0
            outside = float(np.count_nonzero(outside_text)) / (inside_text + float(np.count_nonzero(outside_text)))
        score = support * (1.0 - min(1.0, outside * 10)) * (1.0 - paper_like) + 0.05 * area
        info = (score, method, q, area, support, border_sides, outside, angs)
        if best is None or score > best[0]:
            best = info

    reasons: List[str] = []
    if best is None:
        if rejected.get("paper_outside"):
            reasons.append("The page fills the photo (no separate background); it is kept as framed.")
        else:
            reasons.append("No reliable document outline was found; the photo is kept as framed.")
        return DocumentDetection(False, False, None, None, 0.0, 1.0, False, 0.0, 0.0, reasons=reasons,
                                 candidates_considered=len(cands))

    score, method, q, area, support, border_sides, outside, angs = best
    deviation = float(np.max(np.abs(angs - 90.0)))
    quad_full = (q / scale).astype(np.float64)
    ratio, ratio_method = estimate_aspect_ratio(quad_full, (w, h))
    top = np.linalg.norm(quad_full[1] - quad_full[0])
    bottom = np.linalg.norm(quad_full[2] - quad_full[3])
    out_w = float(max(top, bottom))
    out_h = out_w / max(1e-6, ratio)
    longest = max(out_w, out_h)
    if longest > config.output_max_side:
        f = config.output_max_side / longest
        out_w, out_h = out_w * f, out_h * f
    det = DocumentDetection(
        found=True,
        should_warp=False,
        quad=quad_full.round(1).tolist(),
        method=method,
        confidence=round(float(support), 3),
        area_fraction=round(float(area), 3),
        touches_border=border_sides > 0,
        max_corner_deviation_deg=round(deviation, 2),
        text_outside_fraction=round(float(outside), 4),
        output_size=(int(round(out_w)), int(round(out_h))),
        aspect_ratio=round(float(ratio), 4),
        aspect_method=ratio_method,
        candidates_considered=len(cands),
    )
    on_frame = _corners_on_frame(q, sw, sh, border_tol)
    det.corners_on_frame = len(on_frame)
    if 1 <= len(on_frame) <= 3 and text_small is not None:
        # Evidence of a cropped page: text INSIDE the outline running into the frame edge that the
        # outline touches. A page corner that merely touches the frame is not rejected.
        page_region = np.zeros((sh, sw), np.uint8)
        cv2.fillConvexPoly(page_region, q.astype(np.int32), 255)
        lightness = lab_small[:, :, 0]
        paper_l = float(np.percentile(lightness[page_region > 0], 85)) if np.count_nonzero(page_region) else 0.0
        det.cut_off_edges = [
            e for e in _edges_with_text(cv2.bitwise_and(text_small, page_region), on_frame, sw, sh)
            if _edge_is_paper(lightness, page_region, e, paper_l)]
        det.cut_off = bool(det.cut_off_edges)
        det.outline_reliable = not det.cut_off
    if det.cut_off:
        reasons.append("Part of the page, with text on it, is outside the photo. The photo was not reshaped; "
                       "please retake it with the whole page visible.")
    elif support < 0.55:
        reasons.append("The page outline is not clear enough to correct perspective safely.")
    elif outside > config.max_text_outside_quad_fraction:
        reasons.append("Some text lies outside the detected outline; it was not cropped.")
    elif area >= config.full_frame_area_fraction and deviation < 4.0:
        reasons.append("The page already fills the photo; no perspective correction needed.")
    else:
        det.should_warp = True
    if border_sides:
        reasons.append("Part of the page edge is outside the photo.")
    det.reasons = reasons
    return det


def _corners_on_frame(q: np.ndarray, w: int, h: int, tol: float) -> List[str]:
    """Frame edges (left / top / right / bottom) touched by outline corners, one entry per corner."""
    edges: List[str] = []
    for x, y in np.asarray(q, dtype=np.float64).reshape(4, 2):
        touched = [name for name, hit in (("left", x <= tol), ("top", y <= tol),
                                          ("right", x >= w - 1 - tol), ("bottom", y >= h - 1 - tol)) if hit]
        if touched:
            edges.append(touched[0] if len(touched) == 1 else "+".join(touched))
    return edges


def _edges_with_text(text_mask: Optional[np.ndarray], corner_edges: List[str], w: int, h: int) -> List[str]:
    """Frame edges (among those the outline touches) that text marks run into."""
    if text_mask is None:
        return []
    sides = sorted({e for ce in corner_edges for e in ce.split("+")})
    n, _, stats, _ = cv2.connectedComponentsWithStats((text_mask > 0).astype(np.uint8), connectivity=8)
    st = stats[1:]
    st = st[st[:, 4] >= 2]
    strip = max(2, int(0.01 * max(w, h)))
    touching = {
        "left": st[:, 0] <= strip,
        "top": st[:, 1] <= strip,
        "right": st[:, 0] + st[:, 2] >= w - strip,
        "bottom": st[:, 1] + st[:, 3] >= h - strip,
    }
    return [s for s in sides if int(touching[s].sum()) >= 3]


def _edge_is_paper(lightness: np.ndarray, region: np.ndarray, edge: str, paper_l: float) -> bool:
    """The page area along a frame edge is paper-coloured (not table / carpet / background).

    Paper in shade stays well above 0.6 of the paper level (measured 0.68-0.87 on cut-off pages,
    including real phone photos with a shadowed edge); a textured background inside a wrong outline
    measured 0.37."""
    h, w = lightness.shape[:2]
    strip = max(3, int(0.015 * max(w, h)))
    sl = {"left": (slice(None), slice(0, strip)), "right": (slice(None), slice(w - strip, w)),
          "top": (slice(0, strip), slice(None)), "bottom": (slice(h - strip, h), slice(None))}[edge]
    px = lightness[sl][region[sl] > 0]
    return px.size > 0 and float(np.median(px)) >= 0.6 * paper_l


def warp_document(img: np.ndarray, det: DocumentDetection, scale: float = 1.0) -> np.ndarray:
    """Rectify the page. `scale` enlarges the output in the same warp (single resampling)."""
    quad = np.asarray(det.quad, dtype=np.float32)
    out_w, out_h = int(round(det.output_size[0] * scale)), int(round(det.output_size[1] * scale))
    dst = np.float32([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]])
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(img, m, (out_w, out_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
