"""
Safe image loading with EXIF orientation normalisation.

* Validates the file signature (magic bytes), not just the extension or client MIME type.
* Rejects decompression bombs from the header before any pixel is decoded.
* Decodes very large JPEGs at reduced scale (JPEG draft mode) to bound memory use.
* Applies the EXIF orientation exactly once; the returned pixels carry no EXIF, so no
  later step can rotate the image a second time.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Dict, Optional

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from services.document_prep.config import DocumentPrepConfig, default_config

# EXIF orientation value -> human description of the stored rotation
EXIF_ORIENTATION_NAMES: Dict[int, str] = {
    1: "normal",
    2: "mirrored horizontally",
    3: "rotated 180",
    4: "mirrored vertically",
    5: "mirrored and rotated 90 counter-clockwise",
    6: "rotated 90 clockwise",
    7: "mirrored and rotated 90 clockwise",
    8: "rotated 90 counter-clockwise",
}

_SIGNATURES = (
    (b"\xff\xd8\xff", "JPEG", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "PNG", "image/png"),
    (b"BM", "BMP", "image/bmp"),
    (b"II*\x00", "TIFF", "image/tiff"),
    (b"MM\x00*", "TIFF", "image/tiff"),
)

PIL_FORMATS_ALLOWED = {"JPEG", "MPO", "PNG", "WEBP", "BMP", "TIFF"}


class ImageInputError(ValueError):
    """The uploaded file is not a usable invoice image. The message is safe to show to users."""


@dataclass
class LoadedImage:
    rgb: np.ndarray  # H x W x 3 uint8, EXIF orientation applied, alpha flattened onto white
    mime_type: str
    original_size: tuple  # (width, height) as stored in the file, before EXIF rotation
    decoded_scale: float  # < 1.0 when decoded at reduced resolution
    exif_orientation: Optional[int]
    exif_applied: bool
    notes: list = field(default_factory=list)

    @property
    def size(self) -> tuple:
        return (int(self.rgb.shape[1]), int(self.rgb.shape[0]))


def sniff_image_type(data: bytes) -> Optional[str]:
    """Return the MIME type implied by the file signature, or None."""
    for sig, _fmt, mime in _SIGNATURES:
        if data.startswith(sig):
            return mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_filename(filename: Optional[str], config: DocumentPrepConfig = default_config) -> str:
    """Return a safe display name (basename only). Raises for disallowed extensions."""
    name = PurePath((filename or "").replace("\\", "/")).name.strip()
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')[:120]
    ext = PurePath(name).suffix.lower()
    if ext and ext not in config.allowed_extensions:
        raise ImageInputError(
            f"'{ext}' files are not supported here. Please use a photo (JPG, PNG, WEBP, BMP or TIFF)."
        )
    return name or "invoice-photo"


def load_image(data: bytes, filename: Optional[str] = None, config: DocumentPrepConfig = default_config) -> LoadedImage:
    if not data:
        raise ImageInputError("The photo is empty. Please capture or choose the invoice again.")
    if len(data) > config.max_upload_bytes:
        mb = config.max_upload_bytes // (1024 * 1024)
        raise ImageInputError(f"The photo is larger than {mb} MB. Please use a smaller photo.")
    validate_filename(filename, config)
    mime = sniff_image_type(data)
    if mime is None:
        raise ImageInputError("This file is not a supported image. Please use a JPG, PNG, WEBP, BMP or TIFF photo.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in PIL_FORMATS_ALLOWED:
                raise ImageInputError("This image format is not supported.")
            w, h = img.size
            if w * h > config.max_input_pixels:
                raise ImageInputError("The photo has too many pixels to process safely. Please use a smaller photo.")
            if min(w, h) < config.min_input_side:
                raise ImageInputError(
                    f"The photo is too small ({w}x{h} pixels). Please retake it closer to the invoice."
                )
            notes = []
            decoded_scale = 1.0
            # Decode big JPEGs at 1/2, 1/4 ... scale directly; never below the working size.
            if img.format in ("JPEG", "MPO") and max(w, h) > config.working_max_side * 2:
                target = config.working_max_side
                img.draft("RGB", (max(1, w * target // max(w, h)), max(1, h * target // max(w, h))))
                decoded_scale = img.size[0] / float(w)
                if decoded_scale < 1.0:
                    notes.append(f"decoded at {decoded_scale:.2f} scale to limit memory")
            img.load()
    except ImageInputError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ImageInputError(f"The photo could not be read ({type(exc).__name__}). It may be damaged.") from exc

    exif_orientation: Optional[int] = None
    try:
        exif_orientation = int(img.getexif().get(0x0112) or 0) or None
    except Exception:  # malformed EXIF must not block processing
        exif_orientation = None

    exif_applied = False
    if exif_orientation and exif_orientation != 1:
        try:
            transposed = ImageOps.exif_transpose(img)
            if transposed is not None and transposed is not img:
                img = transposed
                exif_applied = True
        except Exception:
            notes.append("EXIF orientation present but could not be applied; using pixels as stored")

    # Flatten transparency onto white paper; normalise to RGB
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba).convert("RGB")
    elif img.mode == "I;16" or img.mode == "I":
        arr16 = np.asarray(img, dtype=np.float32)
        arr8 = np.clip(arr16 / max(1.0, float(arr16.max())) * 255.0, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr8, "L").convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    rgb = np.array(img, dtype=np.uint8)
    # Exact-size cap after decode (non-JPEG formats cannot be draft-decoded)
    longest = max(rgb.shape[:2])
    if longest > config.working_max_side:
        import cv2

        scale = config.working_max_side / float(longest)
        rgb = cv2.resize(rgb, (max(1, int(rgb.shape[1] * scale)), max(1, int(rgb.shape[0] * scale))),
                         interpolation=cv2.INTER_AREA)
        decoded_scale *= scale
        notes.append(f"resized to {rgb.shape[1]}x{rgb.shape[0]} working resolution")

    return LoadedImage(
        rgb=np.ascontiguousarray(rgb),
        mime_type=mime,
        original_size=(w, h),
        decoded_scale=round(decoded_scale, 4),
        exif_orientation=exif_orientation,
        exif_applied=exif_applied,
        notes=notes,
    )
