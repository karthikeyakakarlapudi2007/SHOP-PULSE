"""
Limits and tunables for the document preparation layer.

Values can be overridden with environment variables so deployments can trade speed for
thoroughness without code changes. Every threshold that drives a decision lives here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class DocumentPrepConfig:
    # ---- Input safety -------------------------------------------------------
    max_upload_bytes: int = _env_int("DOC_PREP_MAX_UPLOAD_BYTES", 25 * 1024 * 1024)
    # Pixel cap applied from the image header before any decode (decompression-bomb guard)
    max_input_pixels: int = _env_int("DOC_PREP_MAX_INPUT_PIXELS", 60_000_000)
    min_input_side: int = 200
    allowed_extensions: FrozenSet[str] = field(
        default_factory=lambda: frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})
    )
    # Longest side used for all processing; larger photos are decoded at reduced scale.
    # The existing OCR pipeline downsizes anything above 3600 px, so there is no gain above this.
    working_max_side: int = _env_int("DOC_PREP_WORKING_MAX_SIDE", 3400)
    # Longest side used for analysis-only steps (orientation, document detection)
    analysis_max_side: int = 1400

    # ---- Orientation ----------------------------------------------------------
    use_ocr_for_orientation: bool = _env_bool("DOC_PREP_OCR_ORIENTATION", True)
    orientation_ocr_max_side: int = 1800
    min_skew_to_correct_deg: float = 0.25
    max_skew_to_correct_deg: float = 30.0

    # ---- Document detection ---------------------------------------------------
    min_document_area_fraction: float = 0.20
    full_frame_area_fraction: float = 0.94
    max_text_outside_quad_fraction: float = 0.02

    # ---- Output ---------------------------------------------------------------
    output_max_side: int = 3400
    target_char_height_px: int = 30  # cap height Tesseract reads best (roughly 20-40 px)
    pdf_dpi: int = 300  # the existing OCR pipeline rasterises PDFs at 300 DPI
    max_pages_per_session: int = _env_int("DOC_PREP_MAX_PAGES", 10)
    max_pdf_bytes: int = 25 * 1024 * 1024  # existing OCR upload limit

    # ---- Variant comparison --------------------------------------------------
    compare_variants_with_ocr: bool = _env_bool("DOC_PREP_COMPARE_VARIANTS", True)
    variant_ocr_margin: float = 0.04  # relative score margin needed to override the default choice
    max_parallel_ocr: int = _env_int("DOC_PREP_MAX_PARALLEL_OCR", 3)

    # ---- Storage --------------------------------------------------------------
    storage_dir: Path = Path(os.environ.get("DOC_PREP_STORAGE_DIR", str(BACKEND_DIR / "storage" / "doc_prep")))
    archive_dir: Path = Path(
        os.environ.get("DOC_PREP_ARCHIVE_DIR", str(BACKEND_DIR / "storage" / "invoice_documents"))
    )
    session_ttl_seconds: int = _env_int("DOC_PREP_SESSION_TTL_SECONDS", 6 * 3600)
    max_sessions_per_user: int = 8
    max_concurrent_jobs: int = _env_int("DOC_PREP_MAX_CONCURRENT_JOBS", 2)


default_config = DocumentPrepConfig()
