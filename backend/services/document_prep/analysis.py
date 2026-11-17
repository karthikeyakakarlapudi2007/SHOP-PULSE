"""
Text-structure analysis shared by quality assessment, orientation detection, deskewing and
document detection.

All measurements are made on character-like connected components, not on whole-image
statistics, so paper texture, wood grain or a dark table do not masquerade as text and do
not distort blur / skew / orientation estimates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def resize_max_side(img: np.ndarray, max_side: int, interpolation: int = cv2.INTER_AREA) -> Tuple[np.ndarray, float]:
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest <= max_side:
        return img, 1.0
    scale = max_side / float(longest)
    return cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=interpolation), scale


def estimate_background(gray: np.ndarray, kernel: Optional[int] = None) -> np.ndarray:
    """Paper / illumination estimate: closing removes dark strokes, blur smooths the result."""
    h, w = gray.shape[:2]
    k = kernel or max(15, (min(h, w) // 25) | 1)
    k = k | 1
    small, scale = resize_max_side(gray, 900)
    ks = max(5, int(round(k * scale)) | 1)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ks, ks))
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, se)
    bg = cv2.medianBlur(bg, min(255, ks | 1) if ks <= 255 else 255)
    bg = cv2.GaussianBlur(bg, (0, 0), max(1.0, ks / 3.0))
    if scale != 1.0:
        bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.maximum(bg, 1)


@dataclass
class TextAnalysis:
    """Result of separating ink from paper and grouping ink into components."""

    ink_mask: np.ndarray  # uint8 0/255, all ink (text + rules)
    text_mask: np.ndarray  # uint8 0/255, character-like components only
    rule_mask: np.ndarray  # uint8 0/255, long thin rulings / borders
    centroids: np.ndarray  # (N, 2) float32 x,y of character components
    boxes: np.ndarray  # (N, 4) int32 x,y,w,h of character components
    char_height: float  # median height of character components (pixels at analysis scale)
    darkness_threshold: float
    ink_contrast: float  # median darkness of strong strokes relative to paper (0..1)
    paper_noise: float  # robust std of darkness on paper (0..1)
    scale: float  # analysis scale relative to the image passed in
    dot_boxes: Optional[np.ndarray] = None  # (M, 4) dot-sized marks next to text: decimal points, commas, i/j dots

    @property
    def n_chars(self) -> int:
        return int(len(self.centroids))


def analyze_text(img: np.ndarray, max_side: int = 1400) -> TextAnalysis:
    gray_full = to_gray(img)
    gray, scale = resize_max_side(gray_full, max_side)
    h, w = gray.shape[:2]
    bg = estimate_background(gray)
    signed = 1.0 - gray.astype(np.float32) / bg.astype(np.float32)
    darkness = np.clip(signed, 0.0, 1.0)

    # Robust paper-noise estimate: MAD of (signed) darkness on paper-level pixels
    paper_px = signed[signed < np.percentile(signed, 70)]
    if paper_px.size:
        med = float(np.median(paper_px))
        noise = float(1.4826 * np.median(np.abs(paper_px - med)))
    else:
        noise = 0.0
    strong = float(np.percentile(darkness, 99.7))
    thr = float(np.clip(max(4.0 * noise + 0.02, 0.30 * strong), 0.06, 0.45))
    ink = (darkness > thr).astype(np.uint8) * 255

    # Long thin rulings (table borders, underlines) are separated so they do not count as text
    min_rule = max(25, int(min(h, w) * 0.06))
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (min_rule, 1)))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_rule)))
    rules = cv2.bitwise_or(horiz, vert)
    rules = cv2.dilate(rules, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    no_rules = cv2.bitwise_and(ink, cv2.bitwise_not(rules))

    n, labels, stats, cents = cv2.connectedComponentsWithStats(no_rules, connectivity=8)
    if n <= 1:
        empty = np.zeros_like(ink)
        return TextAnalysis(ink, empty, rules, np.zeros((0, 2), np.float32), np.zeros((0, 4), np.int32),
                            0.0, thr, 0.0, noise, scale)
    st = stats[1:]
    cw, ch, area = st[:, 2], st[:, 3], st[:, 4]
    fill = area / np.maximum(1, cw * ch)
    longest = np.maximum(cw, ch)
    keep = (
        (area >= 6)
        & (longest >= 4)
        & (ch <= h * 0.12) & (cw <= w * 0.12)
        & (fill >= 0.08)
        & (np.maximum(cw, ch) <= 12 * np.maximum(1, np.minimum(cw, ch)))
    )
    if keep.sum() >= 10:
        heights = np.maximum(cw, ch)[keep].astype(np.float32)  # orientation independent
        char_h = float(np.median(heights))
        # Drop blobs far larger than characters (photos, logos, merged shadows)
        keep &= longest <= max(8.0, char_h * 4.0)
    idx = np.nonzero(keep)[0]
    text = np.isin(labels, idx + 1).astype(np.uint8) * 255 if idx.size else np.zeros_like(ink)
    boxes = st[idx, :4].astype(np.int32)
    centroids = cents[1:][idx].astype(np.float32)
    char_h = float(np.median(np.maximum(boxes[:, 2], boxes[:, 3]))) if idx.size else 0.0
    if idx.size:
        ink_contrast = float(np.median(darkness[text > 0]))
    else:
        ink_contrast = 0.0
    # Dot-sized marks (decimal points, commas, dots of i/j) are too small to count as
    # characters above, but they carry meaning on invoices. Keep the ones that sit next to
    # text so isolated specks of noise are not counted.
    dots = np.zeros((0, 4), np.int32)
    if idx.size and char_h > 0:
        dot_sel = (
            (longest >= 2) & (longest <= max(2.0, 0.35 * char_h)) & (area >= 3) & (fill >= 0.3)
            & (np.maximum(cw, ch) <= 2.5 * np.maximum(1, np.minimum(cw, ch)))
        )
        cand = np.nonzero(dot_sel)[0]
        if cand.size:
            near = cv2.dilate(text, cv2.getStructuringElement(cv2.MORPH_RECT, (int(char_h) | 1, int(char_h) | 1)))
            cc = cents[1:][cand].astype(int)
            inside = near[np.clip(cc[:, 1], 0, h - 1), np.clip(cc[:, 0], 0, w - 1)] > 0
            dots = st[cand[inside], :4].astype(np.int32)
    return TextAnalysis(ink, text, rules, centroids, boxes, char_h, thr, ink_contrast, noise, scale, dots)


# --------------------------------------------------------------------------
# Line direction (docstrum) and projection-profile skew
# --------------------------------------------------------------------------


def docstrum_direction(analysis: TextAnalysis, k: int = 4, max_points: int = 1800) -> Tuple[float, float, int]:
    """Dominant text-line direction from nearest-neighbour angles between characters.

    Within a line, a character's nearest neighbours are the adjacent characters, so the
    histogram of neighbour angles (mod 180) peaks along the line direction (O'Gorman 1993).
    Returns (angle_deg in [-90, 90), confidence 0..1, pairs_used).  0 = horizontal lines.
    """
    pts = analysis.centroids
    if len(pts) < 12:
        return 0.0, 0.0, 0
    if len(pts) > max_points:
        rng = np.random.default_rng(1234)
        pts = pts[rng.choice(len(pts), max_points, replace=False)]
    diff = pts[None, :, :] - pts[:, None, :]
    d2 = (diff ** 2).sum(-1)
    np.fill_diagonal(d2, np.inf)
    kk = min(k, len(pts) - 1)
    nn = np.argpartition(d2, kk, axis=1)[:, :kk]
    rows = np.repeat(np.arange(len(pts)), kk)
    vec = diff[rows, nn.ravel()]
    dist = np.sqrt((vec ** 2).sum(-1))
    ch = max(2.0, analysis.char_height)
    ok = (dist > 0.2 * ch) & (dist < 2.2 * ch)  # neighbours within a word / line
    vec = vec[ok]
    if len(vec) < 10:
        return 0.0, 0.0, int(len(vec))
    ang = np.degrees(np.arctan2(vec[:, 1], vec[:, 0])) % 180.0  # 0..180
    hist, _ = np.histogram(ang, bins=180, range=(0, 180))
    # circular smoothing
    kernel = np.array([1, 2, 3, 2, 1], np.float32)
    padded = np.concatenate([hist[-2:], hist, hist[:2]]).astype(np.float32)
    smooth = np.convolve(padded, kernel, mode="valid")
    peak = int(np.argmax(smooth))
    total = smooth.sum() or 1.0

    def mass(center: int, half: int = 12) -> float:
        idx = [(center + o) % 180 for o in range(-half, half + 1)]
        return float(smooth[idx].sum())

    peak_mass = mass(peak)
    perp_mass = mass((peak + 90) % 180)
    confidence = float(np.clip((peak_mass - perp_mass) / total * 2.0, 0.0, 1.0))
    angle = float(peak + 0.5)
    if angle >= 90.0:
        angle -= 180.0
    return angle, confidence, int(len(vec))


def projection_energy(points: np.ndarray, angle_deg: float, weights: Optional[np.ndarray] = None) -> float:
    """Sum of squared projection-histogram bins when projecting perpendicular to angle_deg."""
    a = np.radians(angle_deg)
    proj = -points[:, 0] * np.sin(a) + points[:, 1] * np.cos(a)
    proj = proj - proj.min()
    hist = np.bincount(proj.astype(np.int64), weights=weights)
    return float((hist.astype(np.float64) ** 2).sum())


def refine_line_angle(mask: np.ndarray, approx_deg: float, search: float = 3.0, step: float = 0.05,
                      max_points: int = 80000) -> Tuple[float, float]:
    """Refine the text-line angle near approx_deg by maximising projection-profile energy.

    Returns (angle_deg, sharpness) where sharpness is peak energy / mean energy in the window.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return approx_deg, 0.0
    pts = np.stack([xs, ys], 1).astype(np.float32)
    if len(pts) > max_points:
        rng = np.random.default_rng(99)
        pts = pts[rng.choice(len(pts), max_points, replace=False)]
    coarse = np.arange(approx_deg - search, approx_deg + search + 1e-6, 0.25)
    energies = np.array([projection_energy(pts, a) for a in coarse])
    best = float(coarse[int(np.argmax(energies))])
    fine = np.arange(best - 0.3, best + 0.3 + 1e-6, step)
    fe = np.array([projection_energy(pts, a) for a in fine])
    best = float(fine[int(np.argmax(fe))])
    sharp = float(fe.max() / max(1e-9, energies.mean()))
    return best, sharp


def rotate_bound(img: np.ndarray, angle_ccw_deg: float, border_value=None,
                 interpolation: int = cv2.INTER_CUBIC, scale: float = 1.0) -> np.ndarray:
    """Rotate by a small angle on an expanded canvas so no pixel of the input is cut off.

    `scale` folds a resize into the same warp, so the page is resampled only once.
    """
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_ccw_deg, scale)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw = int(np.ceil(h * sin + w * cos))
    nh = int(np.ceil(h * cos + w * sin))
    m[0, 2] += nw / 2.0 - w / 2.0
    m[1, 2] += nh / 2.0 - h / 2.0
    if border_value is None:
        border_value = estimate_border_color(img)
    return cv2.warpAffine(img, m, (nw, nh), flags=interpolation, borderMode=cv2.BORDER_CONSTANT,
                          borderValue=border_value)


def estimate_border_color(img: np.ndarray):
    """Median colour of the outermost pixels: a fill colour that blends with the paper."""
    strip = np.concatenate([
        img[:2].reshape(-1, *img.shape[2:]), img[-2:].reshape(-1, *img.shape[2:]),
        img[:, :2].reshape(-1, *img.shape[2:]), img[:, -2:].reshape(-1, *img.shape[2:]),
    ])
    med = np.median(strip, axis=0)
    if np.ndim(med) == 0:
        return int(med)
    return tuple(int(v) for v in med)


def rotate_cardinal_cw(img: np.ndarray, degrees_cw: int) -> np.ndarray:
    k = (int(degrees_cw) // 90) % 4
    if k == 0:
        return img
    return cv2.rotate(img, {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}[k])
