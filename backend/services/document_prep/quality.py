"""
Measurable image-quality assessment for invoice photos.

Every indicator is computed on the text itself (character components found by
analysis.analyze_text) or on the paper around it, and is expressed relative to the
character height where that matters.  That keeps the verdict independent of photo size
and stops paper texture, wood grain or a busy background from being mistaken for blur or
noise in the document.

Indicators
    resolution      character height in pixels (what OCR actually needs), image size
    blur            edge-spread estimate (sigma of a Gaussian edge, from contrast / max
                    gradient) relative to character height, cross-checked with a
                    contrast-normalised Laplacian variance measured only on text regions
    brightness      paper level (bright percentile) and mean luminance
    contrast        median ink darkness relative to the local paper level
    noise           Immerkaer (1996) noise sigma, measured on flat (non-edge) areas only
    illumination    spread of the estimated paper/background level (shadows, gradients)
    rotation/skew   from orientation detection (passed in by the pipeline)
    perspective     corner-angle deviation of the detected page outline (passed in)
    visibility      text cut by the photo edge; area of the detected page
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import cv2
import numpy as np

from services.document_prep.analysis import TextAnalysis, analyze_text, estimate_background, resize_max_side, to_gray

GRADES = ("EXCELLENT", "GOOD", "NEEDS_ENHANCEMENT", "POOR", "UNREADABLE")
SEVERITY_NAMES = {1: "minor", 2: "needs_enhancement", 3: "poor", 4: "unreadable"}


@dataclass
class QualityIssue:
    code: str
    severity: int  # 1 minor .. 4 unreadable
    message: str
    correctable: bool


@dataclass
class QualityReport:
    grade: str
    score: float  # 0..100, higher is better (presentation aid; the grade is rule-based)
    retake_recommended: bool
    summary: str
    metrics: Dict[str, float]
    issues: List[QualityIssue] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["issues"] = [asdict(i) for i in self.issues]
        return d


def immerkaer_noise_sigma(gray: np.ndarray) -> float:
    """Fast noise estimate (Immerkaer 1996), restricted to non-edge pixels."""
    g = gray.astype(np.float32)
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    conv = np.abs(cv2.filter2D(g, -1, kernel, borderType=cv2.BORDER_REFLECT))
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    flat = mag < np.percentile(mag, 60)
    flat[:1, :] = flat[-1:, :] = False
    flat[:, :1] = flat[:, -1:] = False
    if flat.sum() < 100:
        return 0.0
    return float(np.sqrt(np.pi / 2.0) / 6.0 * conv[flat].mean())


def blur_metrics(gray: np.ndarray, analysis: TextAnalysis) -> Dict[str, float]:
    """Edge spread of text strokes. gray must be at the analysis scale."""
    if analysis.n_chars < 10:
        return {"edge_sigma_px": 0.0, "blur_ratio": 1.0, "laplacian_norm": 0.0, "edge_contrast": 0.0}
    region = cv2.dilate(analysis.text_mask, np.ones((5, 5), np.uint8)) > 0
    g = gray.astype(np.float32)
    vals = g[region]
    paper = float(np.percentile(vals, 95))
    ink = float(np.percentile(vals, 3))
    contrast = max(1.0, paper - ink)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3, scale=1.0 / 8.0)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3, scale=1.0 / 8.0)
    mag = cv2.magnitude(gx, gy)[region]
    g_peak = float(np.percentile(mag, 97))
    # A step edge of height C blurred by a Gaussian (sigma) has peak slope C / (sigma*sqrt(2*pi))
    sigma = contrast / max(1e-3, g_peak * np.sqrt(2 * np.pi))
    lap = cv2.Laplacian(g, cv2.CV_32F, ksize=3)[region]
    lap_norm = float(lap.var() / (contrast ** 2))
    char_h = max(1.0, analysis.char_height)
    # ~0.6 px of edge spread is intrinsic to anti-aliased sampling; only the excess is blur
    excess = float(np.sqrt(max(0.0, sigma * sigma - 0.36)))
    return {
        "edge_sigma_px": round(sigma, 3),
        "blur_ratio": round(excess / char_h, 4),
        # Laplacian energy scales with 1/size^2; normalising by character size makes small
        # sharp text and large sharp text comparable
        "laplacian_norm": round(lap_norm * (char_h / 10.0) ** 2, 4),
        "edge_contrast": round(contrast, 1),
    }


def assess_quality(
    img: np.ndarray,
    analysis: Optional[TextAnalysis] = None,
    region_mask: Optional[np.ndarray] = None,
    geometry: Optional[Dict[str, float]] = None,
) -> QualityReport:
    """Grade a page image. region_mask (same size as img, 0/255) limits paper statistics to the
    document when a background is visible. geometry carries rotation / skew / perspective."""
    a = analysis or analyze_text(img)
    gray_full = to_gray(img)
    gray, scale = resize_max_side(gray_full, 1400)
    if abs(scale - a.scale) > 1e-3:
        a = analyze_text(img)
        gray, scale = resize_max_side(gray_full, 1400)
    region = None
    if region_mask is not None:
        region = cv2.resize(region_mask, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
        if region.sum() < 0.05 * region.size:
            region = None

    h_full, w_full = gray_full.shape[:2]
    char_h_full = a.char_height / max(a.scale, 1e-6)
    metrics: Dict[str, float] = {
        "width": float(w_full),
        "height": float(h_full),
        "megapixels": round(w_full * h_full / 1e6, 2),
        "characters_found": float(a.n_chars),
        "char_height_px": round(char_h_full, 1),
    }
    metrics.update(blur_metrics(gray, a))

    sel = gray[region] if region is not None else gray.ravel()
    metrics["mean_luminance"] = round(float(sel.mean()), 1)
    metrics["paper_level"] = round(float(np.percentile(sel, 90)), 1)
    metrics["ink_contrast"] = round(float(a.ink_contrast), 3)
    noise_src = gray.copy()
    if region is not None:
        ys, xs = np.nonzero(region)
        noise_src = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    metrics["noise_sigma"] = round(immerkaer_noise_sigma(noise_src), 2)
    bg = estimate_background(gray, kernel=max(15, int(a.char_height * 3) | 1))
    bsel = bg[region] if region is not None else bg.ravel()
    hi = float(np.percentile(bsel, 98))
    lo = float(np.percentile(bsel, 2))
    metrics["illumination_unevenness"] = round((hi - lo) / max(1.0, hi), 3)

    # Visibility: ink (text or table rulings) running into a paper-coloured photo edge means
    # part of the invoice is outside the photo. Only meaningful when the page fills the frame
    # (no separate background); a textured table at the edge is not paper-coloured.
    metrics["edges_cut"] = 0.0
    metrics["text_at_edge_fraction"] = 0.0
    if a.n_chars and region is None:
        ink = (a.ink_mask > 0).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        st = stats[1:]
        st = st[st[:, 4] >= 8]
        hh, ww = ink.shape[:2]
        paper_ref = float(np.percentile(gray, 90))
        strip = max(3, int(0.01 * min(hh, ww)))
        edges = {
            "left": (st[:, 0] <= 1, gray[:, :strip]),
            "top": (st[:, 1] <= 1, gray[:strip, :]),
            "right": (st[:, 0] + st[:, 2] >= ww - 1, gray[:, -strip:]),
            "bottom": (st[:, 1] + st[:, 3] >= hh - 1, gray[-strip:, :]),
        }
        cut = 0
        touching_total = 0
        for touch, strip_px in edges.values():
            k = int(touch.sum())
            touching_total += k
            if k >= 3 and float(np.median(strip_px)) >= 0.85 * paper_ref:
                cut += 1
        metrics["edges_cut"] = float(cut)
        metrics["text_at_edge_fraction"] = round(touching_total / max(1.0, float(len(st))), 4)
    if geometry:
        metrics.update({k: float(v) for k, v in geometry.items() if v is not None})

    issues: List[QualityIssue] = []

    def add(code: str, sev: int, msg: str, correctable: bool) -> None:
        issues.append(QualityIssue(code, sev, msg, correctable))

    n = a.n_chars
    if n < 15:
        add("no_text", 4, "No readable text was found in the photo.", False)
    ch = char_h_full
    br = metrics["blur_ratio"]
    if n >= 15:
        if ch < 5:
            add("resolution", 4, "The text is far too small in this photo to be read.", False)
        elif ch < 7:
            add("resolution", 3, "The text is very small; move the camera closer and retake.", False)
        elif ch < 10:
            add("resolution", 2, "The text is small; the image will be enlarged for reading.", True)
        elif ch < 13:
            add("resolution", 1, "The text is fairly small.", True)

        # Two independent blur indicators; an "unreadable" verdict needs both to agree.
        bl = metrics["laplacian_norm"]
        sev_sigma = 3 if br > 0.16 else 2 if br > 0.10 else 1 if br > 0.065 else 0
        sev_lap = 4 if bl < 0.08 else 3 if bl < 0.15 else 2 if bl < 0.8 else 1 if bl < 1.5 else 0
        blur_sev = max(sev_sigma, sev_lap)
        if blur_sev >= 3 and min(sev_sigma, sev_lap) < 2:
            blur_sev = 2
        if blur_sev == 4:
            add("blur", 4, "The photo is too blurry to read. Hold the phone steady and retake.", False)
        elif blur_sev == 3:
            add("blur", 3, "The photo is blurry; some characters may be misread. A retake is recommended.", False)
        elif blur_sev == 2:
            add("blur", 2, "The photo is slightly soft; gentle sharpening will be applied.", True)
        elif blur_sev == 1:
            add("blur", 1, "Very slight softness.", True)

        ic = metrics["ink_contrast"]
        if ic < 0.10:
            add("contrast", 3, "The print is extremely faint.", False)
        elif ic < 0.30:
            add("contrast", 2, "The print is faint; contrast will be increased.", True)
        elif ic < 0.45:
            add("contrast", 1, "Contrast is a little low.", True)

    pl = metrics["paper_level"]
    if pl < 50:
        add("brightness", 3, "The photo is very dark. Retake with more light.", False)
    elif pl < 110:
        add("brightness", 2, "The photo is dark; brightness will be corrected.", True)
    elif pl < 150:
        add("brightness", 1, "The photo is slightly dark.", True)

    ns = metrics["noise_sigma"]
    if ns > 18:
        add("noise", 3, "The photo is very grainy.", False)
    elif ns > 7:
        add("noise", 2, "The photo is grainy; noise will be reduced.", True)
    elif ns > 4:
        add("noise", 1, "Slight grain.", True)

    un = metrics["illumination_unevenness"]
    if un > 0.40:
        add("shadow", 2, "Strong shadow or uneven light; lighting will be evened out.", True)
    elif un > 0.18:
        add("shadow", 1, "Lighting is a little uneven.", True)

    if metrics["edges_cut"] >= 1 or (geometry or {}).get("cut_off"):
        add("cut_off", 3, "Part of the invoice seems to be outside the photo. Please retake with the whole page visible.", False)

    if geometry:
        rot = geometry.get("rotation_cw") or 0
        if rot:
            add("rotation", 1, f"The page was turned {int(rot)} degrees.", True)
        sk = abs(geometry.get("skew_deg") or 0.0)
        if sk >= 0.5:
            add("skew", 1, f"The page is tilted by {sk:.1f} degrees.", True)
        pdv = geometry.get("perspective_deviation_deg") or 0.0
        if pdv > 12:
            add("perspective", 2, "The photo was taken at a strong angle.", True)
        elif pdv > 4:
            add("perspective", 1, "The photo was taken at an angle.", True)

    max_sev = max((i.severity for i in issues), default=0)
    grade = {0: "EXCELLENT", 1: "GOOD", 2: "NEEDS_ENHANCEMENT", 3: "POOR", 4: "UNREADABLE"}[max_sev]
    retake = max_sev >= 3
    penalty = sum({1: 4, 2: 12, 3: 30, 4: 60}[i.severity] for i in issues)
    score = float(max(0.0, 100.0 - penalty))
    if grade == "UNREADABLE":
        summary = "This photo cannot be read reliably. Please retake it; enhancement cannot restore detail the camera did not capture."
    elif grade == "POOR":
        summary = "Poor photo. We will try to improve it, but a retake is strongly recommended."
    elif grade == "NEEDS_ENHANCEMENT":
        summary = "Readable after correction. Automatic improvements will be applied."
    elif grade == "GOOD":
        summary = "Good photo. Only small corrections are needed."
    else:
        summary = "Excellent photo."
    return QualityReport(grade, round(score, 1), retake, summary, metrics, issues)


def worst_grade(grades: List[str]) -> str:
    return max(grades, key=GRADES.index) if grades else "EXCELLENT"
