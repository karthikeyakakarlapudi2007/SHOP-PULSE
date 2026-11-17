"""
Measured acceptance tests: OCR of the original photo vs. OCR of the prepared page, both through
the EXISTING engine path (AdaptiveImageProcessor + tesseract.js), against exact ground truth.

Skipped when the OCR engine (node + tesseract.js) is not installed.
"""

import cv2
import pytest

from doc_prep_dataset import build_dataset
from services.document_prep import prepare_page
from services.document_prep.ocr_scoring import (
    character_error_rate,
    critical_token_recall,
    ocr_engine_available,
    run_pipeline_ocr,
)

pytestmark = pytest.mark.skipif(not ocr_engine_available(), reason="OCR engine not installed")

DATA = build_dataset()
RECOVERABLE = [cid for cid in DATA if cid != "17_unrecoverable"]


@pytest.fixture(scope="module")
def results():
    cache = {}

    def get(cid):
        if cid not in cache:
            case = DATA[cid]
            pages = []
            for i, img in enumerate(case.pages):
                ok, enc = cv2.imencode(".png", img)
                prepared = prepare_page(enc.tobytes(), "page.png")
                pages.append({
                    "prepared": prepared,
                    "baseline_text": run_pipeline_ocr(img).text,
                    "prepared_text": run_pipeline_ocr(prepared.variants[prepared.recommended_variant]).text,
                })
            gt = case.ground_truth_text
            base = "\n\n".join(p["baseline_text"] for p in pages)
            prep = "\n\n".join(p["prepared_text"] for p in pages)
            cache[cid] = {
                "pages": pages,
                "cer": (character_error_rate(gt, base), character_error_rate(gt, prep)),
                "critical": (critical_token_recall(case.critical_tokens, base),
                             critical_token_recall(case.critical_tokens, prep)),
            }
        return cache[cid]

    return get


@pytest.mark.parametrize("cid", RECOVERABLE)
def test_prepared_page_reads_at_least_as_well(results, cid):
    r = results(cid)
    base_cer, prep_cer = r["cer"]
    base_crit, prep_crit = r["critical"]
    n = len(DATA[cid].critical_tokens)
    assert prep_cer <= base_cer + 0.02, f"CER regressed {base_cer:.3f} -> {prep_cer:.3f}"
    assert prep_crit >= base_crit - 1.0 / n, f"critical tokens regressed {base_crit:.3f} -> {prep_crit:.3f}"
    assert prep_cer < 0.30, f"prepared CER still high: {prep_cer:.3f}"


@pytest.mark.parametrize("cid", ["04_rotated_180", "05_rotated_270", "15_table_borders_tilted_photo", "09_low_light"])
def test_unreadable_today_becomes_readable(results, cid):
    base_cer, prep_cer = results(cid)["cer"]
    assert base_cer > 0.7 and prep_cer < 0.25


@pytest.mark.parametrize("cid", [c for c in DATA if "rotation" in DATA[c].tags or c in ("01_clear_portrait", "02_landscape")])
def test_orientation_with_ocr_evidence(results, cid):
    case = DATA[cid]
    for i, page in enumerate(results(cid)["pages"]):
        expected = case.expected_rotation_cw
        if cid == "12_multi_page":
            expected = (0, 270)[i]
        assert page["prepared"].metadata["orientation"]["auto_rotation_cw"] == expected


def test_unrecoverable_photo_is_flagged_not_faked():
    ok, enc = cv2.imencode(".png", DATA["17_unrecoverable"].pages[0])
    md = prepare_page(enc.tobytes(), "p.png").metadata
    assert md["quality_before"]["grade"] == "UNREADABLE"
    assert md["retake_recommended"]
