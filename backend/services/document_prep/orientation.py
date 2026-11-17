"""
Page orientation (0 / 90 / 180 / 270) and fine skew detection.

Evidence used, strongest first:

1. Text-line direction from character nearest-neighbour statistics (docstrum).  This tells
   horizontal (0/180) from vertical (90/270) text using the characters themselves, so a wide
   photo of a landscape invoice is NOT rotated just because it is wider than tall.
2. OCR evidence from the existing Tesseract engine: the two remaining candidates (upright
   vs. upside down) are read and the one producing confident, plausible words wins.
   tesseract.js orientation detection (OSD) needs osd.traineddata, which ShopPulse does not
   ship, so readability is compared directly instead.
3. Typographic evidence: in upright Latin text, ascenders/capitals (b d f h k l t A-Z 0-9)
   put more ink above the x-height band than descenders (g j p q y) put below it.
   Used when OCR is unavailable and as a tie-breaker.

Aspect ratio and document geometry are recorded but never decide the rotation on their own.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import cv2
import numpy as np

from services.document_prep.analysis import (
    TextAnalysis,
    analyze_text,
    docstrum_direction,
    refine_line_angle,
    resize_max_side,
    rotate_bound,
    rotate_cardinal_cw,
    to_gray,
)
from services.document_prep.ocr_scoring import OcrFunction

logger = logging.getLogger(__name__)


@dataclass
class OrientationResult:
    rotation_cw: int  # clockwise rotation to apply to make the page upright
    skew_deg: float  # residual line angle after the cardinal rotation (image coords, + = clockwise)
    confidence: float  # 0..1 for the cardinal decision
    line_direction_deg: float
    line_direction_confidence: float
    method: str
    needs_confirmation: bool
    evidence: Dict[str, object] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)


def _wrap_line_angle(a: float) -> float:
    """Wrap an undirected line angle into [-90, 90)."""
    a = (a + 90.0) % 180.0 - 90.0
    return a


def ascender_descender_score(text_mask: np.ndarray, char_height: float) -> Dict[str, float]:
    """+ means upright, - means upside down. Text lines must already be horizontal."""
    if text_mask is None or not np.any(text_mask):
        return {"score": 0.0, "lines": 0, "weight": 0.0}
    prof = (text_mask > 0).sum(axis=1).astype(np.float32)
    if prof.max() <= 0:
        return {"score": 0.0, "lines": 0, "weight": 0.0}
    k = max(1, int(round(char_height * 0.08)))
    smooth = np.convolve(prof, np.ones(k) / k, mode="same") if k > 1 else prof
    active = smooth > max(1.0, 0.02 * smooth.max())
    bands = []
    start = None
    for y, on in enumerate(active):
        if on and start is None:
            start = y
        elif not on and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, len(active)))

    num = 0.0
    den = 0.0
    used = 0
    min_h = max(4, int(char_height * 0.5))
    max_h = max(min_h + 1, int(char_height * 2.6))
    for y0, y1 in bands:
        hgt = y1 - y0
        if hgt < min_h or hgt > max_h:
            continue  # noise or merged lines
        p = prof[y0:y1]
        core = np.nonzero(p >= 0.55 * p.max())[0]
        if core.size == 0:
            continue
        upper = float(p[: core[0]].sum())
        lower = float(p[core[-1] + 1:].sum())
        if upper + lower <= 0:
            continue
        num += upper - lower
        den += upper + lower
        used += 1
    score = num / den if den > 0 else 0.0
    return {"score": round(float(score), 4), "lines": used, "weight": round(den, 1)}


def _deskewed_view(img: np.ndarray, rotation_cw: int, line_angle_after: float) -> np.ndarray:
    view = rotate_cardinal_cw(img, rotation_cw)
    if abs(line_angle_after) >= 0.2:
        view = rotate_bound(view, line_angle_after, border_value=255 if view.ndim == 2 else (255, 255, 255))
    return view


def detect_orientation(
    img: np.ndarray,
    analysis: Optional[TextAnalysis] = None,
    ocr_fn: Optional[OcrFunction] = None,
    ocr_max_side: int = 1800,
) -> OrientationResult:
    """Decide the clockwise cardinal rotation and residual skew for a page image (BGR or gray)."""
    a = analysis or analyze_text(img)
    reasons: List[str] = []
    evidence: Dict[str, object] = {"characters_found": a.n_chars, "char_height_px": round(a.char_height / max(a.scale, 1e-6), 1)}
    h, w = img.shape[:2]
    evidence["aspect_ratio"] = round(w / float(h), 3)

    if a.n_chars < 15:
        return OrientationResult(0, 0.0, 0.0, 0.0, 0.0, "insufficient_text", True, evidence,
                                 ["Too little text was found to decide the page orientation."])

    line_angle, line_conf, pairs = docstrum_direction(a)
    evidence.update({"docstrum_angle": round(line_angle, 2), "docstrum_confidence": round(line_conf, 3),
                     "neighbour_pairs": pairs})
    vertical = abs(line_angle) > 45.0
    base = 90 if vertical else 0  # rotating 90 CW turns vertical lines horizontal
    # After rotating the image clockwise by `base`, line angles (image coords, y down) grow by `base`.
    approx_after = _wrap_line_angle(line_angle + base)

    # Refine the residual skew on the text mask rotated by the base rotation
    mask_rot = rotate_cardinal_cw(a.text_mask, base)
    refined, sharpness = refine_line_angle(mask_rot, approx_after, search=2.5)
    evidence["projection_sharpness"] = round(sharpness, 3)
    skew = refined

    # Typographic up/down evidence on the deskewed mask
    deskewed_mask = rotate_bound(mask_rot, skew, border_value=0, interpolation=cv2.INTER_NEAREST) if abs(skew) >= 0.2 else mask_rot
    typo = ascender_descender_score(deskewed_mask, a.char_height)
    evidence["ascender_descender"] = typo
    typo_score = float(typo["score"])
    typo_choice = base if typo_score >= 0 else (base + 180) % 360
    typo_strength = min(1.0, abs(typo_score) / 0.25) * min(1.0, typo["lines"] / 4.0)

    # Weak typographic evidence never flips a page on its own: without a clear signal the
    # page keeps the orientation implied by its text-line direction.
    choice = typo_choice if typo_strength >= 0.35 else base
    method = "text_lines+typography" if typo_strength >= 0.35 else "text_lines"
    confidence = 0.5 + 0.5 * typo_strength

    if ocr_fn is not None:
        gray = to_gray(img)
        small, _ = resize_max_side(gray, ocr_max_side)
        readouts = {}
        try:
            cands = (base, (base + 180) % 360)
            views = [_deskewed_view(small, c, skew) for c in cands]
            with ThreadPoolExecutor(max_workers=2) as pool:  # separate OCR worker processes
                for cand, readout in zip(cands, pool.map(ocr_fn, views)):
                    readouts[cand] = readout
            s_base = readouts[base].score
            s_flip = readouts[(base + 180) % 360].score
            evidence["ocr_scores"] = {str(base): s_base, str((base + 180) % 360): s_flip}
            best = base if s_base >= s_flip else (base + 180) % 360
            hi, lo = max(s_base, s_flip), min(s_base, s_flip)
            ratio = (hi + 1.0) / (lo + 1.0)
            evidence["ocr_ratio"] = round(ratio, 3)
            if hi >= 8.0 and ratio >= 1.5:
                choice = best
                method = "text_lines+ocr"
                confidence = min(1.0, 0.6 + 0.2 * np.log2(ratio))
                if best != typo_choice and typo_strength > 0.5:
                    reasons.append("Typography and OCR disagreed on up/down; OCR evidence was used.")
                    confidence *= 0.85
            else:
                reasons.append("OCR could not clearly tell upright from upside down.")
                confidence = min(confidence, 0.55)
        except Exception as exc:  # OCR is supporting evidence only
            logger.warning("Orientation OCR check failed: %s", exc)
            evidence["ocr_error"] = type(exc).__name__

    # A 180 degree turn leaves undirected line angles unchanged, so `skew` holds for either choice.
    line_conf_factor = 0.5 + 0.5 * line_conf
    confidence = float(np.clip(confidence * line_conf_factor, 0.0, 1.0))
    if line_conf < 0.3:
        reasons.append("Text lines are not clearly aligned in one direction.")
    needs_confirmation = confidence < 0.6
    if needs_confirmation:
        reasons.append("Automatic orientation is uncertain. Please check the page is upright.")
    return OrientationResult(
        rotation_cw=int(choice % 360),
        skew_deg=round(float(skew), 2),
        confidence=round(confidence, 3),
        line_direction_deg=round(line_angle, 2),
        line_direction_confidence=round(line_conf, 3),
        method=method,
        needs_confirmation=needs_confirmation,
        evidence=evidence,
        reasons=reasons,
    )


def measure_residual_skew(img: np.ndarray) -> Dict[str, float]:
    """Post-correction verification: remaining line angle and whether lines are horizontal."""
    a = analyze_text(img)
    if a.n_chars < 15:
        return {"line_angle": 0.0, "horizontal": 1.0, "confidence": 0.0}
    ang, conf, _ = docstrum_direction(a)
    if abs(ang) <= 45:
        refined, _ = refine_line_angle(a.text_mask, ang, search=2.0)
    else:
        refined = ang
    return {"line_angle": round(float(refined), 2), "horizontal": float(abs(refined) <= 45), "confidence": round(conf, 3)}
