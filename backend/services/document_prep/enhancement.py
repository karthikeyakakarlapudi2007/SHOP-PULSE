"""
Adaptive enhancement driven by quality diagnostics.

Nothing is applied blindly: each operation has an explicit trigger measured on the page,
and every applied operation is recorded with the measurement that justified it.  After
enhancement the result is *verified*: if character components or small marks (decimal
points, dots of i/j, commas) were lost, the enhancement is reduced or abandoned.

Operations (in order)
    grayscale             always for the enhanced variant (the OCR engine reads luminance)
    illumination          divide by an estimated paper background (shadows, low light)
    denoise               non-local means, only when grain was measured
    upscale               cubic resize when characters are smaller than OCR prefers
    contrast              percentile stretch anchored on ink and paper; CLAHE only for very faint print
    sharpen               unsharp mask restricted to text regions, only for moderate blur
    binarize              adaptive threshold - produced as a separate variant, never forced
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.document_prep.analysis import TextAnalysis, analyze_text, estimate_background, to_gray
from services.document_prep.config import DocumentPrepConfig, default_config
from services.document_prep.quality import QualityReport


@dataclass
class EnhancementStep:
    name: str
    reason: str
    params: Dict[str, float] = field(default_factory=dict)


@dataclass
class EnhancementResult:
    image: np.ndarray  # uint8 grayscale
    steps: List[EnhancementStep]
    verification: Dict[str, float]
    reverted: List[str] = field(default_factory=list)
    upscale_factor: float = 1.0


def _odd(n: float) -> int:
    n = int(round(n))
    return n if n % 2 else n + 1


def correct_illumination(gray: np.ndarray, char_h: float) -> np.ndarray:
    bg = estimate_background(gray, kernel=_odd(max(15, char_h * 2.5)))
    out = gray.astype(np.float32) / bg.astype(np.float32) * 245.0
    return np.clip(out, 0, 255).astype(np.uint8)


def contrast_stretch(gray: np.ndarray, text_mask_full: Optional[np.ndarray]) -> Tuple[np.ndarray, Dict[str, float]]:
    """Map ink to near-black and paper to near-white without clipping faint strokes away."""
    paper = float(np.percentile(gray, 90))
    if text_mask_full is not None and np.count_nonzero(text_mask_full) > 50:
        ink = float(np.percentile(gray[text_mask_full > 0], 8))
    else:
        ink = float(np.percentile(gray, 1))
    if paper - ink < 8:
        return gray, {"ink": ink, "paper": paper, "applied": 0.0}
    lut = np.clip((np.arange(256, dtype=np.float32) - ink) * (235.0 / (paper - ink)) + 10.0, 0, 255)
    # Keep paper slightly below pure white so faint marks above the paper level are not erased
    lut = np.where(np.arange(256) >= paper, np.minimum(255, 245 + (np.arange(256) - paper) * 0.5), lut)
    return cv2.LUT(gray, lut.astype(np.uint8)), {"ink": round(ink, 1), "paper": round(paper, 1), "applied": 1.0}


def selective_unsharp(gray: np.ndarray, sigma: float, amount: float, text_region: np.ndarray) -> np.ndarray:
    g = gray.astype(np.float32)
    blurred = cv2.GaussianBlur(g, (0, 0), sigma)
    sharp = np.clip(g + amount * (g - blurred), 0, 255)
    w = cv2.GaussianBlur((text_region > 0).astype(np.float32), (0, 0), 2.0)
    return np.clip(g * (1 - w) + sharp * w, 0, 255).astype(np.uint8)


def small_mark_count(analysis: TextAnalysis, ref_char_height: Optional[float] = None) -> int:
    """Count dot-sized marks next to text (decimal points, commas, i/j dots).

    They must survive enhancement. ref_char_height (at the same scale as `analysis`) keeps
    the size yardstick fixed between the before and after images.
    """
    marks = analysis.dot_boxes if analysis.dot_boxes is not None else np.zeros((0, 4), np.int32)
    if analysis.n_chars:
        b = analysis.boxes
        ch = max(2.0, ref_char_height or analysis.char_height)
        longest = np.maximum(b[:, 2], b[:, 3])
        small_chars = int(((longest <= 0.35 * ch) & (longest >= 2)).sum())
    else:
        small_chars = 0
    if marks.size and ref_char_height:
        longest_m = np.maximum(marks[:, 2], marks[:, 3])
        return int((longest_m <= max(2.0, 0.35 * ref_char_height)).sum()) + small_chars
    return int(len(marks)) + small_chars


def plan_and_enhance(
    img: np.ndarray,
    report: QualityReport,
    analysis: Optional[TextAnalysis] = None,
    config: DocumentPrepConfig = default_config,
    allow: Optional[Dict[str, bool]] = None,
) -> EnhancementResult:
    allow = dict(allow or {})
    if allow.pop("only_resolution", False):
        allow.update({"illumination": False, "denoise": False, "contrast": False, "sharpen": False})
    a = analysis or analyze_text(img)
    m = report.metrics
    gray = to_gray(img).copy()
    steps: List[EnhancementStep] = [EnhancementStep("grayscale", "OCR reads luminance; colour carries no extra text detail")]
    char_h_full = float(m.get("char_height_px") or (a.char_height / max(a.scale, 1e-6)))

    # 1. Illumination / shadows / low light
    uneven = m.get("illumination_unevenness", 0.0)
    paper = m.get("paper_level", 255.0)
    if allow.get("illumination", True) and (uneven > 0.12 or paper < 170):
        gray = correct_illumination(gray, max(6.0, char_h_full))
        steps.append(EnhancementStep(
            "illumination_correction",
            f"uneven lighting {uneven:.2f} / paper level {paper:.0f} measured",
            {"unevenness": uneven, "paper_level": paper}))

    # 2. Denoise only measured grain (NLM keeps stroke edges; strength follows the estimate)
    noise = m.get("noise_sigma", 0.0)
    if allow.get("denoise", True) and noise > 4.0:
        h = float(np.clip(noise * 0.9, 3.0, 12.0))
        gray = cv2.fastNlMeansDenoising(gray, None, h=h, templateWindowSize=7, searchWindowSize=15)
        steps.append(EnhancementStep("denoise", f"noise sigma {noise:.1f} measured", {"h": round(h, 2)}))

    # 3. Upscale small text (cannot add detail; helps OCR segment small glyphs and decimals)
    factor = 1.0
    if allow.get("upscale", True) and 0 < char_h_full < 0.8 * config.target_char_height_px:
        factor = min(3.0, config.target_char_height_px / char_h_full)
        longest = max(gray.shape[:2])
        factor = min(factor, config.output_max_side / float(longest))
        if factor >= 1.15:
            gray = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
            steps.append(EnhancementStep(
                "upscale", f"character height {char_h_full:.1f}px is below the {config.target_char_height_px}px OCR target",
                {"factor": round(factor, 3)}))
        else:
            factor = 1.0

    # Text regions at the current resolution (for stretch statistics and selective sharpening)
    a_now = analyze_text(gray)
    text_full = cv2.resize(a_now.text_mask, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)

    # 4. Contrast: faint print, dim photos or after illumination flattening
    ink_c = m.get("ink_contrast", 1.0)
    if allow.get("contrast", True) and (ink_c < 0.45 or any(s.name == "illumination_correction" for s in steps)):
        gray, info = contrast_stretch(gray, text_full)
        if info.get("applied"):
            steps.append(EnhancementStep("contrast_stretch", f"ink contrast {ink_c:.2f} measured", info))
        if ink_c < 0.20:
            clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            steps.append(EnhancementStep("clahe", f"very faint print (ink contrast {ink_c:.2f})", {"clip_limit": 1.8}))

    # 5. Selective sharpening for moderate blur only (strong blur cannot be undone; heavy
    #    sharpening creates halos that break thin decimal points)
    br = m.get("blur_ratio", 0.0)
    lap = m.get("laplacian_norm", 10.0)
    moderate_blur = (0.06 < br <= 0.16) or (0.15 <= lap < 1.5)
    if allow.get("sharpen", True) and moderate_blur and noise <= 8.0:
        sigma = float(np.clip(m.get("edge_sigma_px", 1.0) * factor / max(a.scale, 1e-6), 0.8, 3.0))
        amount = float(np.clip(0.4 + (1.5 - min(lap, 1.5)) * 0.4, 0.4, 0.9))
        region = cv2.dilate(text_full, np.ones((5, 5), np.uint8))
        gray = selective_unsharp(gray, sigma, amount, region)
        steps.append(EnhancementStep(
            "selective_sharpen", f"moderate blur (edge ratio {br:.3f}, laplacian {lap:.2f})",
            {"sigma": round(sigma, 2), "amount": round(amount, 2)}))

    # Verification: characters and small marks must survive
    after = analyze_text(gray)
    before_ref = analyze_text(cv2.resize(to_gray(img), (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_CUBIC)) if factor != 1.0 else a
    verification = {
        "chars_before": float(before_ref.n_chars),
        "chars_after": float(after.n_chars),
        "small_marks_before": float(small_mark_count(before_ref)),
        "small_marks_after": float(small_mark_count(after, before_ref.char_height * after.scale / max(before_ref.scale, 1e-6))),
        "ink_contrast_before": round(before_ref.ink_contrast, 3),
        "ink_contrast_after": round(after.ink_contrast, 3),
    }
    return EnhancementResult(gray, steps, verification, upscale_factor=factor)


def enhancement_is_safe(v: Dict[str, float]) -> Tuple[bool, str]:
    cb, ca = v["chars_before"], v["chars_after"]
    sb, sa = v["small_marks_before"], v["small_marks_after"]
    if cb >= 20 and ca < 0.85 * cb:
        return False, f"character components dropped from {int(cb)} to {int(ca)}"
    if sb >= 8 and sa < 0.85 * sb:
        return False, f"small marks (decimal points, dots) dropped from {int(sb)} to {int(sa)}"
    if cb >= 20 and ca > 1.8 * cb:
        return False, f"enhancement created noise ({int(cb)} -> {int(ca)} components)"
    return True, "characters and small marks preserved"


def binarize(gray: np.ndarray, char_h: float) -> np.ndarray:
    block = _odd(max(15, char_h * 1.6))
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 12)
