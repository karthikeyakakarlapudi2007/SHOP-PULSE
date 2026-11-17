"""
HEIC/HEIF support in the document preparation layer (decode-only, via pi-heif).

Fixtures: tests/fixtures/heic (see README there for how they were made).
"""

import dataclasses
from pathlib import Path

import cv2
import numpy as np
import pytest

from services.document_prep import loader as loader_mod
from services.document_prep.loader import ImageInputError, load_image, sniff_image_type
from services.document_prep.orientation import detect_orientation
from services.document_prep.pipeline import PrepOptions, prepare_page

FIX = Path(__file__).resolve().parent / "fixtures" / "heic"
NO_OCR = PrepOptions(use_ocr=False)

pytestmark = pytest.mark.skipif(not loader_mod.heif_supported(), reason="HEIF decoder (pi-heif) not installed")


def read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_heic_is_recognised_by_signature_not_extension():
    assert sniff_image_type(read("invoice_upright.heic")) == "image/heic"
    # A renamed HEIC is still decoded as HEIC; a fake .heic is rejected
    assert load_image(read("invoice_upright.heic"), "photo.jpg").mime_type == "image/heic"
    with pytest.raises(ImageInputError):
        load_image(b"\x00\x00\x00\x18ftypavif" + b"\x00" * 64, "x.heic")  # AVIF brand: not supported


def test_upright_heic_decodes_without_rotation():
    loaded = load_image(read("invoice_upright.heic"), "a.heic")
    assert loaded.size == (744, 1052)
    assert not loaded.exif_applied
    assert detect_orientation(cv2.cvtColor(loaded.rgb, cv2.COLOR_RGB2BGR)).rotation_cw == 0


def test_heic_orientation_is_applied_exactly_once():
    loaded = load_image(read("invoice_exif6.heic"), "IMG_0001.HEIC")
    assert loaded.exif_orientation == 6 and loaded.exif_applied
    assert loaded.size == (744, 1052)  # upright portrait, not rotated a second time
    # Same pixels as the upright file (lossy codec, so compare loosely)
    ref = load_image(read("invoice_upright.heic"), "a.heic").rgb.astype(np.int16)
    assert np.abs(loaded.rgb.astype(np.int16) - ref).mean() < 6
    page = prepare_page(read("invoice_exif6.heic"), "IMG_0001.HEIC", NO_OCR)
    assert page.metadata["orientation"]["auto_rotation_cw"] == 0


def test_sideways_heic_without_metadata_is_turned_by_text_evidence():
    loaded = load_image(read("invoice_sideways_noexif.heic"), "a.heic")
    assert loaded.size == (1052, 744) and not loaded.exif_applied
    page = prepare_page(read("invoice_sideways_noexif.heic"), "a.heic", NO_OCR)
    # Stored content was turned 90 degrees counter-clockwise, so it needs 90 degrees clockwise
    assert page.metadata["orientation"]["auto_rotation_cw"] == 90
    corrected = cv2.cvtColor(page.variants["corrected"], cv2.COLOR_BGR2GRAY).astype(np.int16)
    ref = cv2.cvtColor(load_image(read("invoice_upright.heic"), "a.heic").rgb, cv2.COLOR_RGB2GRAY).astype(np.int16)
    assert corrected.shape == ref.shape
    assert np.abs(corrected - ref).mean() < 6  # the same upright page


def test_heic_with_alpha_is_flattened_onto_white():
    loaded = load_image(read("invoice_rgba.heic"), "a.heic")
    assert loaded.rgb.ndim == 3 and loaded.rgb.shape[2] == 3
    assert loaded.rgb[5, 5].min() >= 240  # paper stays white


def test_heic_pixel_limit_is_checked_before_decoding():
    tiny_cfg = dataclasses.replace(loader_mod.default_config, max_input_pixels=100_000)
    with pytest.raises(ImageInputError, match="too many pixels"):
        load_image(read("invoice_upright.heic"), "a.heic", tiny_cfg)


def test_clear_message_when_decoder_is_missing(monkeypatch):
    monkeypatch.setattr(loader_mod, "heif_supported", lambda: False)
    with pytest.raises(ImageInputError, match="HEIC photos cannot be read"):
        load_image(read("invoice_upright.heic"), "a.heic")


def test_jpeg_and_png_paths_unchanged():
    img = np.full((900, 700, 3), 245, np.uint8)
    cv2.putText(img, "INVOICE 58.75", (40, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
    for ext in (".jpg", ".png"):
        ok, enc = cv2.imencode(ext, img)
        loaded = load_image(enc.tobytes(), "x" + ext)
        assert loaded.mime_type == {"jpg": "image/jpeg", "png": "image/png"}[ext[1:]]
        assert loaded.size == (700, 900) and not loaded.exif_applied
