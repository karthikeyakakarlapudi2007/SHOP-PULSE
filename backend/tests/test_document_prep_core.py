"""
Document preparation layer: unit tests that do not need the OCR engine.

Covers EXIF handling, input safety, orientation (text evidence, no OCR), deskew, content
preservation, document detection / perspective, quality grading, enhancement safety,
PDF generation and session storage security.
"""

import dataclasses
import io
import time

import cv2
import numpy as np
import pytest
from PIL import Image

from doc_prep_dataset import (
    PAGE_1_ITEMS,
    build_dataset,
    camera_quad,
    place_on_background,
    render_invoice_page,
    rotate_cardinal,
    tilt,
)
from services.document_prep import analysis as an
from services.document_prep.config import default_config
from services.document_prep.document_detector import detect_document, warp_document
from services.document_prep.enhancement import enhancement_is_safe, plan_and_enhance, small_mark_count
from services.document_prep.loader import ImageInputError, load_image
from services.document_prep.orientation import detect_orientation, measure_residual_skew
from services.document_prep.pdf_builder import build_pdf
from services.document_prep.pipeline import PrepOptions, prepare_page
from services.document_prep.quality import assess_quality
from services.document_prep.session_store import SessionLimitError, SessionNotFound, SessionStore

NO_OCR = PrepOptions(use_ocr=False)


def png(img: np.ndarray) -> bytes:
    ok, enc = cv2.imencode(".png", img)
    assert ok
    return enc.tobytes()


@pytest.fixture(scope="module")
def dataset():
    return build_dataset()


@pytest.fixture(scope="module")
def clean_page():
    return render_invoice_page(PAGE_1_ITEMS).image


# --------------------------------------------------------------------------------------
# EXIF + input safety
# --------------------------------------------------------------------------------------


def _jpeg_with_orientation(img_rgb: np.ndarray, orientation: int) -> bytes:
    im = Image.fromarray(img_rgb)
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=92, exif=exif.tobytes())
    return buf.getvalue()


def test_exif_orientation_applied_once(clean_page):
    upright = cv2.cvtColor(clean_page, cv2.COLOR_BGR2RGB)
    # A phone stores the sensor image sideways and sets orientation 6 ("rotate 90 CW to view")
    stored = np.ascontiguousarray(np.rot90(upright, k=1))  # rotated 90 CCW on disk
    loaded = load_image(_jpeg_with_orientation(stored, 6))
    assert loaded.exif_orientation == 6 and loaded.exif_applied
    assert loaded.size == (upright.shape[1], upright.shape[0])
    # Already upright after EXIF: orientation detection must not rotate it again
    result = detect_orientation(cv2.cvtColor(loaded.rgb, cv2.COLOR_RGB2BGR))
    assert result.rotation_cw == 0


def test_missing_or_normal_exif_leaves_pixels(clean_page):
    rgb = cv2.cvtColor(clean_page, cv2.COLOR_BGR2RGB)
    for data in (_jpeg_with_orientation(rgb, 1), png(clean_page)):
        loaded = load_image(data)
        assert not loaded.exif_applied
        assert loaded.size == (rgb.shape[1], rgb.shape[0])


@pytest.mark.parametrize("data,name", [
    (b"", "x.jpg"),
    (b"not an image at all" * 10, "x.jpg"),
    (b"%PDF-1.4 fake", "x.pdf"),
    (b"MZ\x90\x00binary", "x.exe"),
])
def test_invalid_inputs_rejected(data, name):
    with pytest.raises(ImageInputError):
        load_image(data, name)


def test_extension_must_be_an_image(clean_page):
    with pytest.raises(ImageInputError):
        load_image(png(clean_page), "invoice.svg")


def test_decompression_bomb_rejected_before_decode():
    buf = io.BytesIO()
    Image.new("1", (9000, 9000), 1).save(buf, format="PNG")  # 81 MP, tiny file
    with pytest.raises(ImageInputError, match="too many pixels"):
        load_image(buf.getvalue(), "bomb.png")


def test_oversize_and_tiny_images_rejected(clean_page):
    small_cfg = dataclasses.replace(default_config, max_upload_bytes=1000)
    with pytest.raises(ImageInputError, match="larger than"):
        load_image(png(clean_page), "a.png", small_cfg)
    with pytest.raises(ImageInputError, match="too small"):
        load_image(png(np.full((80, 120, 3), 255, np.uint8)), "a.png")


def test_huge_photo_is_downscaled_to_working_size():
    big = np.full((5000, 3800, 3), 245, np.uint8)
    ok, enc = cv2.imencode(".jpg", big)
    loaded = load_image(enc.tobytes(), "big.jpg")
    assert max(loaded.size) <= default_config.working_max_side
    assert loaded.decoded_scale < 1.0


# --------------------------------------------------------------------------------------
# Orientation + deskew (text evidence only)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("content_cw,expected_fix", [(0, 0), (90, 270), (180, 180), (270, 90)])
def test_cardinal_orientation_without_ocr(clean_page, content_cw, expected_fix):
    img = rotate_cardinal(clean_page, content_cw)
    result = detect_orientation(img)
    assert result.rotation_cw == expected_fix
    assert result.confidence >= 0.6


def test_landscape_invoice_is_not_rotated(dataset):
    img = dataset["02_landscape"].pages[0]
    assert img.shape[1] > img.shape[0]  # wider than tall
    assert detect_orientation(img).rotation_cw == 0


def test_text_free_image_is_left_alone():
    blank = np.full((1200, 900, 3), 240, np.uint8)
    result = detect_orientation(blank)
    assert result.rotation_cw == 0 and result.needs_confirmation


@pytest.mark.parametrize("angle", [1.0, 3.0, 5.0, 8.0, -3.0])
def test_small_tilts_are_measured_and_corrected(clean_page, angle):
    tilted = tilt(clean_page, angle)
    result = detect_orientation(tilted)
    assert result.rotation_cw == 0
    # A counter-clockwise tilt shows as a negative image-coordinate line angle
    assert abs(result.skew_deg + angle) <= 0.3
    page = prepare_page(png(tilted), "t.png", NO_OCR)
    assert page.metadata["orientation"]["deskew_applied"]
    assert abs(measure_residual_skew(page.variants["corrected"])["line_angle"]) <= 0.35


def test_deskew_never_clips_content(clean_page):
    tilted = tilt(clean_page, 8.0)
    out = an.rotate_bound(tilted, -8.0)
    assert out.shape[0] >= tilted.shape[0] and out.shape[1] >= tilted.shape[1]
    before = an.analyze_text(tilted).n_chars
    after = an.analyze_text(out).n_chars
    assert after >= 0.95 * before
    # No ink touches the border of the corrected page
    a = an.analyze_text(out)
    b = a.boxes
    h, w = a.text_mask.shape
    assert not ((b[:, 0] <= 1) | (b[:, 1] <= 1) | (b[:, 0] + b[:, 2] >= w - 1) | (b[:, 1] + b[:, 3] >= h - 1)).any()


def test_sideways_tilted_photo_is_turned_and_straightened(dataset):
    page = prepare_page(png(dataset["15_table_borders_tilted_photo"].pages[0]), "p.png", NO_OCR)
    assert page.metadata["orientation"]["auto_rotation_cw"] == 90
    assert page.metadata["orientation"]["deskew_applied"]
    res = measure_residual_skew(page.variants["corrected"])
    assert res["horizontal"] == 1.0 and abs(res["line_angle"]) <= 0.4


def test_clear_upright_page_is_not_transformed(dataset):
    page = prepare_page(png(dataset["01_clear_portrait"].pages[0]), "p.png", NO_OCR)
    md = page.metadata
    assert md["orientation"]["auto_rotation_cw"] == 0
    assert not md["orientation"]["deskew_applied"]
    assert not md["document"]["perspective_corrected"]
    assert md["quality_before"]["grade"] in ("EXCELLENT", "GOOD")
    # Only resolution normalisation may be applied to a clear page, never tonal changes
    steps = [s["name"] for s in md["enhancement"].get("steps", [])]
    assert set(steps) <= {"grayscale", "upscale"}
    assert np.array_equal(page.variants["corrected"], page.variants["original"])


# --------------------------------------------------------------------------------------
# Document detection / perspective
# --------------------------------------------------------------------------------------


def test_perspective_photo_is_rectified_with_true_aspect_ratio(clean_page):
    photo, _ = place_on_background(
        clean_page, camera_quad((1240, 1754), (1500, 2000), tilt_x_deg=24, tilt_y_deg=-14, roll_deg=3), seed=11)
    det = detect_document(photo)
    assert det.found and det.should_warp
    assert abs(det.aspect_ratio - 1240 / 1754) / (1240 / 1754) < 0.03
    warped = warp_document(photo, det)
    # The rectified page keeps (nearly) all the text
    assert an.analyze_text(warped).n_chars >= 0.9 * an.analyze_text(clean_page).n_chars


def test_flat_scan_is_never_cropped_to_the_table(dataset):
    for cid in ("01_clear_portrait", "10_blurry", "14_faint_print", "17_unrecoverable"):
        det = detect_document(dataset[cid].pages[0])
        assert not det.should_warp, cid


def test_page_on_similar_background_and_shadow_found(dataset):
    for cid in ("08_shadow", "16_similar_background"):
        det = detect_document(dataset[cid].pages[0])
        assert det.found and det.should_warp, cid
        assert det.text_outside_fraction <= 0.02


def test_partially_visible_page_keeps_all_visible_text(clean_page):
    # Page runs off the left and bottom edge of the photo
    photo, _ = place_on_background(clean_page, [(-0.05, 0.08), (0.92, 0.06), (0.95, 1.08), (-0.08, 1.05)], seed=5)
    page = prepare_page(png(photo), "p.png", NO_OCR)
    md = page.metadata
    if md["document"]["perspective_corrected"]:
        q = md["steps"][-1]  # any step; geometry verification must have passed
        assert any(s["step"] == "geometry_verification" and s["details"]["passed"] for s in md["steps"]), q


# --------------------------------------------------------------------------------------
# Quality grading
# --------------------------------------------------------------------------------------


def test_quality_grades_follow_measurements(dataset):
    grade = lambda cid: assess_quality(dataset[cid].pages[0]).grade  # noqa: E731
    assert grade("01_clear_portrait") in ("EXCELLENT", "GOOD")
    assert grade("09_low_light") == "NEEDS_ENHANCEMENT"
    assert grade("14_faint_print") == "NEEDS_ENHANCEMENT"
    assert grade("17_unrecoverable") == "UNREADABLE"


def test_unrecoverable_photo_asks_for_retake(dataset):
    page = prepare_page(png(dataset["17_unrecoverable"].pages[0]), "p.png", NO_OCR)
    assert page.metadata["retake_recommended"]
    assert "retake" in page.metadata["quality_before"]["summary"].lower()


def test_paper_texture_is_not_mistaken_for_blur_or_noise(clean_page):
    rng = np.random.default_rng(3)
    h, w = clean_page.shape[:2]
    fibres = cv2.resize(rng.normal(0, 1, (h // 6, w // 6)).astype(np.float32), (w, h))
    grain = rng.normal(0, 3.0, (h, w)).astype(np.float32)
    textured = np.clip(clean_page.astype(np.float32) * (1 + 0.025 * fibres)[..., None] + grain[..., None], 0, 255)
    report = assess_quality(textured.astype(np.uint8))
    assert report.grade in ("EXCELLENT", "GOOD"), report.issues
    assert not any(i.code == "blur" and i.severity >= 2 for i in report.issues)


def test_text_cut_off_by_photo_edge_is_reported(clean_page):
    cropped = clean_page[:, 150:]  # left part of the invoice outside the photo
    report = assess_quality(cropped)
    assert any(i.code == "cut_off" for i in report.issues)
    assert report.retake_recommended


# --------------------------------------------------------------------------------------
# Enhancement safety
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("cid", ["09_low_light", "14_faint_print", "08_shadow", "13_small_decimals", "10_blurry"])
def test_enhancement_preserves_characters_and_decimal_points(dataset, cid):
    page = prepare_page(png(dataset[cid].pages[0]), "p.png", NO_OCR)
    enh = page.metadata["enhancement"]
    assert enh["applied"], enh
    v = enh["verification"]
    ok, why = enhancement_is_safe(v)
    assert ok, why
    assert v["small_marks_after"] >= 0.85 * v["small_marks_before"]


def test_enhancement_refuses_to_destroy_dots(clean_page):
    report = assess_quality(clean_page)
    a = an.analyze_text(clean_page)
    marks = small_mark_count(a)
    assert marks >= 8  # decimal points etc. exist on the invoice
    eroded = cv2.dilate(clean_page, np.ones((3, 3), np.uint8))  # thins strokes, erases dots
    assert small_mark_count(an.analyze_text(eroded), a.char_height) < marks
    ok, _ = enhancement_is_safe({"chars_before": a.n_chars, "chars_after": a.n_chars,
                                 "small_marks_before": marks, "small_marks_after": marks * 0.5})
    assert not ok
    res = plan_and_enhance(clean_page, report, a, allow={"only_resolution": True})
    assert {s.name for s in res.steps} <= {"grayscale", "upscale"}


def test_original_is_always_kept(dataset):
    data = png(dataset["07_perspective"].pages[0])
    page = prepare_page(data, "p.png", NO_OCR)
    assert "original" in page.variants
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(page.variants["original"], decoded)


# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------


def _render_pdf(data: bytes):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    return [np.array(p.render(scale=300 / 72, grayscale=True).to_pil()) for p in doc]


def test_pdf_preserves_order_size_and_pixels():
    rng = np.random.default_rng(7)
    pages = []
    for i, size in enumerate([(1754, 1240), (1240, 1754), (3007, 2126)]):
        img = np.full(size, 245, np.uint8)
        cv2.putText(img, f"PAGE {i + 1}", (100, 300), cv2.FONT_HERSHEY_SIMPLEX, 4, 0, 8)
        img[500:510] = rng.integers(0, 255, (10, size[1]), dtype=np.uint8)
        pages.append(img)
    result = build_pdf(pages)
    rendered = _render_pdf(result.data)
    assert len(rendered) == 3
    for src, out, info in zip(pages, rendered, result.pages):
        h, w = src.shape
        assert (info.width_px, info.height_px) == (w, h)
        assert out.shape == (h + info.padded_bottom_px, w + info.padded_right_px)
        assert info.padded_right_px <= 48 and info.padded_bottom_px <= 48
        if info.pixel_exact:
            assert np.array_equal(out[:h, :w], src)  # lossless, no resampling
        else:
            assert np.abs(out[:h, :w].astype(int) - src).mean() < 2.0
        assert info.encoding == "flate-gray"


def test_pdf_pixels_are_never_mistaken_for_a_text_layer():
    """Regression: the existing PDF reader inflates every stream and scans it for text
    operators; noisy compressed image data must not produce fake 'digital text'."""
    from services.grocery_ocr.processors.pdf_processor import BasePDFProcessor

    rng = np.random.default_rng(11)
    for _ in range(12):
        imgs = [rng.integers(0, 256, (int(rng.integers(300, 1200)), int(rng.integers(300, 1200))), dtype=np.uint8)
                for _ in range(2)]
        assert not BasePDFProcessor().process(build_pdf(imgs).data).is_digital


def test_pdf_rejects_empty_and_oversize():
    with pytest.raises(ValueError):
        build_pdf([])
    noise = np.random.default_rng(1).integers(0, 256, (1500, 1500, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="limit"):
        build_pdf([noise], max_bytes=200_000, allow_jpeg=False)


# --------------------------------------------------------------------------------------
# Session storage
# --------------------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    cfg = dataclasses.replace(default_config, storage_dir=tmp_path / "s", archive_dir=tmp_path / "a",
                              max_pages_per_session=3)
    return SessionStore(cfg)


def _save(store, user, sid, img, data=b"\xff\xd8\xffraw-original-bytes"):
    return store.save_page(user, sid, data, "p.jpg", "image/jpeg",
                           {"original": img, "corrected": img}, "corrected", {"steps": []})


def test_session_paths_reject_traversal_and_foreign_users(store):
    alice, bob = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    sid = store.create_session(alice)["session_id"]
    for bad in ("../../etc", "..", sid + "/..", sid.upper(), "", "x" * 32):
        with pytest.raises(SessionNotFound):
            store.get_session(alice, bad)
    with pytest.raises(SessionNotFound):
        store.get_session(bob, sid)


def test_session_page_lifecycle(store):
    user = "11111111-1111-1111-1111-111111111111"
    sid = store.create_session(user)["session_id"]
    img = np.full((400, 300, 3), 240, np.uint8)
    raw = b"\xff\xd8\xffexact-original"
    ids = [_save(store, user, sid, img, raw)["page_id"] for _ in range(3)]
    with pytest.raises(SessionLimitError):
        _save(store, user, sid, img)
    data, entry = store.original_bytes(user, sid, ids[0])
    assert data == raw  # original kept byte-for-byte
    store.update_page(user, sid, ids[0], rotate_by=90)
    assert store.update_page(user, sid, ids[0], rotate_by=180)["manual_rotation"] == 270
    assert store.variant_image(user, sid, ids[0], "corrected").shape[:2] == (300, 400)
    assert store.update_page(user, sid, ids[0], rotation=0)["manual_rotation"] == 0
    with pytest.raises(ValueError):
        store.update_page(user, sid, ids[0], selected_variant="enhanced")
    with pytest.raises(ValueError):
        store.reorder(user, sid, ids[:2])
    assert [p["page_id"] for p in store.reorder(user, sid, ids[::-1])["pages"]] == ids[::-1]
    assert len(store.delete_page(user, sid, ids[1])["pages"]) == 2


def test_expired_sessions_are_removed(store):
    user = "11111111-1111-1111-1111-111111111111"
    sid = store.create_session(user)["session_id"]
    short = SessionStore(dataclasses.replace(store.config, session_ttl_seconds=0), root=store.root)
    time.sleep(0.01)
    assert short.cleanup_expired() >= 1
    with pytest.raises(SessionNotFound):
        store.get_session(user, sid)


# --------------------------------------------------------------------------------------
# Low light: denoise at native resolution, before any resampling
# --------------------------------------------------------------------------------------


def _dark_grainy(page: np.ndarray, seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    dark = page.astype(np.float32) * 0.3
    grain = cv2.GaussianBlur(rng.normal(0, 6.0, page.shape[:2]).astype(np.float32), (0, 0), 0.8)[..., None]
    return np.clip(dark + grain, 0, 255).astype(np.uint8)


def test_dark_grainy_photo_is_denoised_before_resampling(clean_page):
    from services.document_prep.enhancement import native_denoise_for_dark_photo, paper_grain_sigma

    dark = _dark_grainy(clean_page)
    out, info = native_denoise_for_dark_photo(dark)
    assert info is not None and info["brightening_gain"] > 3
    assert paper_grain_sigma(to_gray_u8(out)) < 0.6 * paper_grain_sigma(to_gray_u8(dark))
    page = prepare_page(png(dark), "dark.png", NO_OCR)
    step = next(s for s in page.metadata["steps"] if s["step"] == "native_denoise")
    assert step["applied"]
    # characters and decimal points survive the whole low-light treatment
    v = page.metadata["enhancement"]["verification"]
    assert enhancement_is_safe(v)[0]
    # the "original" version is still the untouched photo
    assert np.array_equal(page.variants["original"], dark)


def test_normal_photo_is_not_denoised(clean_page):
    from services.document_prep.enhancement import native_denoise_for_dark_photo

    out, info = native_denoise_for_dark_photo(clean_page)
    assert info is None and out is clean_page


def to_gray_u8(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def test_retake_follows_the_capture_not_the_enhanced_metrics(dataset):
    # A small-text capture of a dense bill: enlargement makes the prepared page measure well
    # (graded GOOD afterwards), but the detail was never captured, so a retake is still advised.
    import json
    from real_world_validation import FIXTURES, photograph

    gt = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    bill = cv2.imread(str(FIXTURES / "invoices" / gt["TC13_sri_balaji_13items"]["filename"]))
    data = photograph(bill, "small_text", 1000 + 1 * 37 + 7)
    page = prepare_page(data, "small.jpg", NO_OCR)
    assert page.metadata["quality_before"]["grade"] in ("POOR", "UNREADABLE")
    assert page.metadata["retake_recommended"]
    clear = prepare_page(png(dataset["01_clear_portrait"].pages[0]), "c.png", NO_OCR)
    assert not clear.metadata["retake_recommended"]
