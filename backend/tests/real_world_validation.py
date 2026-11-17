"""
Real-world validation of the invoice photo preparation layer.

Compares, for every case, the photo exactly as a shop owner would upload it today against the
page prepared by the document preparation layer. Both are read by the EXISTING OCR engine and
extraction pipeline (unchanged), and measured against ground truth:

* OCR level   - CER and WER (when a ground-truth transcript is available), word recall of the
                expected product-name words, and critical-token recall (rates, amounts and
                quantities as printed, decimals included).
* Extraction  - line items whose product name, quantity, rate and amount are ALL correct, plus
                field-level counts.

Two sources of cases:

1. Real photographs (preferred):
       python tests/real_world_validation.py --photos /path/to/folder
   The folder holds the photos and a manifest.json:
       {
         "case_id": {
           "files": ["page1.jpg", "page2.heic"],          # in page order
           "condition": "sideways / low light / ...",      # free text, for the report
           "items": [{"product_name": "Tata Salt 1kg", "quantity": 20, "purchase_price": 22.0,
                      "printed_amount": 440.0}, ...],
           "ground_truth_text": "optional full transcript for CER/WER",
           "critical_tokens": ["optional", "extra", "tokens"]
         }
       }

2. Simulated camera captures (default when no folder is given): the repository's real invoice
   layouts (tests/fixtures/ground_truth) photographed by a physical camera model - pinhole
   perspective, background, uneven light and hard shadows, vignetting, focus/motion blur,
   light-dependent sensor noise, white-balance cast and JPEG. These are clearly SIMULATED and
   are reported as such.

    cd backend && .venv/bin/python tests/real_world_validation.py [--photos DIR] [--md OUT.md] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from doc_prep_dataset import camera_quad, place_on_background  # noqa: E402
from services.document_prep import prepare_page  # noqa: E402
from services.document_prep.loader import load_image  # noqa: E402
from services.document_prep.ocr_scoring import (  # noqa: E402
    bag_of_words_recall,
    character_error_rate,
    normalize_text,
    run_pipeline_ocr,
    word_error_rate,
)
from services.document_prep.pdf_builder import build_pdf  # noqa: E402
from services.grocery_ocr.engines.ocr_engine import TesseractOCREngine  # noqa: E402
from services.grocery_ocr.pipeline.invoice_pipeline import InvoicePipeline  # noqa: E402

FIXTURES = HERE / "fixtures" / "ground_truth"


@dataclass
class Case:
    case_id: str
    layout: str
    condition: str
    pages: List[bytes]  # encoded photos, in page order, exactly as uploaded
    items: List[dict]
    ground_truth_text: Optional[str] = None
    extra_tokens: List[str] = field(default_factory=list)
    simulated: bool = True


# --------------------------------------------------------------------------------------
# Camera model
# --------------------------------------------------------------------------------------


def _illumination(h: int, w: int, rng: np.random.Generator, strength: float, shadow: bool) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    angle = rng.uniform(0, 2 * np.pi)
    grad = (np.cos(angle) * (xx / w - 0.5) + np.sin(angle) * (yy / h - 0.5))
    light = 1.0 - strength * (grad - grad.min()) / max(1e-6, grad.max() - grad.min())
    vignette = 1.0 - 0.22 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    light *= vignette
    if shadow:
        mask = np.zeros((h, w), np.float32)
        x0 = rng.uniform(0.35, 0.55) * w
        pts = np.array([[x0, 0], [x0 + 0.25 * w, 0], [x0 + 0.05 * w, h], [x0 - 0.35 * w, h]], np.int32)
        cv2.fillConvexPoly(mask, pts, 1.0)
        mask = cv2.GaussianBlur(mask, (0, 0), max(3.0, 0.012 * w))
        light *= 1.0 - 0.5 * mask
    return light


def photograph(page_bgr: np.ndarray, condition: str, seed: int) -> bytes:
    """Simulate a phone photo of a printed page under the given condition; returns JPEG bytes."""
    rng = np.random.default_rng(seed)
    ph, pw = page_bgr.shape[:2]
    landscape = pw > ph
    canvas = (2000, 1500) if landscape else (1500, 2000)
    tilt_x, tilt_y, roll, fill = rng.uniform(-8, 8), rng.uniform(-6, 6), rng.uniform(-1.5, 1.5), 0.86
    if condition == "perspective":
        tilt_x, tilt_y = rng.choice([-1, 1]) * rng.uniform(22, 28), rng.choice([-1, 1]) * rng.uniform(10, 16)
    elif condition == "tilted":
        roll = rng.choice([-1, 1]) * rng.uniform(5, 8)
    elif condition == "small_text":
        fill = 0.5
    quad = camera_quad((pw, ph), canvas, tilt_x, tilt_y, roll, fill=fill)
    bg_colors = [(70, 95, 125), (60, 60, 60), (150, 170, 185), (45, 70, 50)]
    photo, _ = place_on_background(page_bgr, quad, canvas, bg_colors[seed % len(bg_colors)], seed=seed,
                                   texture=10.0)
    h, w = photo.shape[:2]
    img = photo.astype(np.float32)
    gain = 0.32 if condition == "low_light" else rng.uniform(0.85, 1.0)
    light = _illumination(h, w, rng, strength=0.35 if condition in ("shadow", "low_light") else 0.15,
                          shadow=condition == "shadow")
    img *= (light * gain)[..., None]
    img *= np.array([0.92, 0.98, 1.04], np.float32)  # warm indoor white balance (BGR)
    focus = 1.6 if condition == "blurry" else rng.uniform(0.6, 0.9)
    img = cv2.GaussianBlur(img, (0, 0), focus)
    if condition == "blurry":
        k = np.zeros((7, 7), np.float32)
        k[3, :] = 1.0 / 7.0
        img = cv2.filter2D(img, -1, cv2.warpAffine(k, cv2.getRotationMatrix2D((3, 3), rng.uniform(0, 180), 1), (7, 7)))
    shot = rng.normal(0, 1, img.shape).astype(np.float32) * np.sqrt(np.maximum(img, 0) * 0.08)
    read = rng.normal(0, 7.0 if condition == "low_light" else 2.0, img.shape).astype(np.float32)
    img = np.clip(img + shot + read, 0, 255).astype(np.uint8)
    if condition == "sideways":
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif condition == "upside_down":
        img = cv2.rotate(img, cv2.ROTATE_180)
    if condition == "small_text":
        img = cv2.resize(img, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return enc.tobytes()


SIM_LAYOUTS = [
    "TC02_bordered_image", "TC13_sri_balaji_13items", "TC15_decimal_quantities", "TC16_borderless_table",
    "TC17_multi_tier_gst", "TC20_faded_thermal_receipt", "TC25_split_column_headers",
    "TC26_promotional_scheme", "TC31_high_density_compact", "TC32_alternate_column_order",
]
SIM_CONDITIONS = ["sideways", "upside_down", "low_light", "shadow", "perspective", "tilted", "blurry", "small_text"]


def simulated_cases(layouts: Sequence[str] = SIM_LAYOUTS, conditions: Sequence[str] = SIM_CONDITIONS) -> List[Case]:
    gt = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    cases: List[Case] = []
    for li, key in enumerate(layouts):
        page = cv2.imread(str(FIXTURES / "invoices" / gt[key]["filename"]), cv2.IMREAD_COLOR)
        for ci, cond in enumerate(conditions):
            cases.append(Case(f"{key}__{cond}", key, cond, [photograph(page, cond, 1000 + li * 37 + ci)],
                              gt[key]["items"]))
    # Multi-page: two different invoices photographed as one document, second page sideways
    p1 = cv2.imread(str(FIXTURES / "invoices" / gt["TC24_dairy_and_staples"]["filename"]), cv2.IMREAD_COLOR)
    p2 = cv2.imread(str(FIXTURES / "invoices" / gt["TC29_flours_and_pulses"]["filename"]), cv2.IMREAD_COLOR)
    cases.append(Case("multi_page__TC24+TC29", "TC24 + TC29", "multi_page (page 2 sideways)",
                      [photograph(p1, "tilted", 77), photograph(p2, "sideways", 78)],
                      gt["TC24_dairy_and_staples"]["items"] + gt["TC29_flours_and_pulses"]["items"]))
    return cases


def real_photo_cases(folder: Path) -> List[Case]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    cases = []
    for cid, entry in manifest.items():
        cases.append(Case(cid, entry.get("layout", "real"), entry.get("condition", "real photo"),
                          [(folder / f).read_bytes() for f in entry["files"]], entry["items"],
                          entry.get("ground_truth_text"), entry.get("critical_tokens", []), simulated=False))
    return cases


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _fmt(v: float) -> str:
    return f"{v:.2f}"


def critical_tokens(items: List[dict], extra: Sequence[str] = ()) -> List[str]:
    tokens = list(extra)
    for it in items:
        for key in ("purchase_price", "printed_amount", "mrp"):
            if it.get(key) is not None:
                tokens.append(_fmt(float(it[key])))
        q = it.get("quantity")
        if q is not None and float(q) != int(q):
            tokens.append(f"{float(q):g}")
    return tokens


def token_recall(tokens: Sequence[str], text: str) -> float:
    if not tokens:
        return 1.0
    flat = (text or "").replace(",", "")
    found = sum(1 for t in tokens if re.search(r"(?<![\d.])" + re.escape(t.replace(",", "")) + r"(?![\d])", flat))
    return found / len(tokens)


def name_word_recall(items: List[dict], text: str) -> float:
    ref = " ".join(it["product_name"] for it in items)
    return bag_of_words_recall(ref, text)


def score_items(extracted, truth: List[dict]) -> Dict[str, int]:
    got = [(_norm_name(i.normalized_product_name or i.raw_product_name), i.quantity, i.purchase_price, i.printed_amount)
           for i in extracted]
    out = {"lines": len(truth), "all_fields": 0, "name": 0, "quantity": 0, "rate": 0, "amount": 0}
    used = set()
    for t in truth:
        tn = _norm_name(t["product_name"])
        best = None
        for idx, (name, q, p, a) in enumerate(got):
            if idx in used or not name or not (tn in name or name in tn):
                continue
            best = idx
            break
        if best is None:
            continue
        used.add(best)
        _, q, p, a = got[best]
        q_ok = q is not None and abs(float(q) - float(t["quantity"])) < 1e-6
        p_ok = p is not None and abs(float(p) - float(t["purchase_price"])) < 0.011
        a_ok = t.get("printed_amount") is None or (a is not None and abs(float(a) - float(t["printed_amount"])) < 0.011)
        out["name"] += 1
        out["quantity"] += int(q_ok)
        out["rate"] += int(p_ok)
        out["amount"] += int(a_ok)
        out["all_fields"] += int(q_ok and p_ok and a_ok)
    return out


# --------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------


def run_case(case: Case, pipeline: InvoicePipeline) -> dict:
    # Baseline: what /invoices/extract receives today (one photo; several photos cannot be sent
    # as one invoice today, so each page is read on its own and the results are combined).
    base_text, base_items = [], []
    prep_text, prep_imgs, prep_meta = [], [], []
    t_prep = 0.0
    for i, data in enumerate(case.pages):
        photo = cv2.cvtColor(load_image(data, f"p{i}.jpg").rgb, cv2.COLOR_RGB2BGR)
        base_text.append(run_pipeline_ocr(photo).text)
        try:
            base_items += pipeline.process(data, f"photo{i}.jpg").items
        except Exception:
            pass
        t = time.perf_counter()
        prepared = prepare_page(data, f"photo{i}.jpg")
        t_prep += time.perf_counter() - t
        variant = prepared.variants[prepared.recommended_variant]
        prep_imgs.append(variant)
        prep_text.append(run_pipeline_ocr(variant).text)
        md = prepared.metadata
        prep_meta.append({
            "rotation_cw": md["orientation"]["auto_rotation_cw"],
            "skew_deg": md["orientation"]["skew_deg"],
            "perspective": md["document"]["perspective_corrected"],
            "quality": f"{md['quality_before']['grade']} -> {md['quality_after']['grade']}",
            "variant": prepared.recommended_variant,
            "retake": md["retake_recommended"],
        })
    try:
        prep_items = pipeline.process(build_pdf(prep_imgs).data, "scan.pdf").items
    except Exception:
        prep_items = []
    btxt, ptxt = "\n\n".join(base_text), "\n\n".join(prep_text)
    tokens = critical_tokens(case.items, case.extra_tokens)
    row = {
        "case": case.case_id, "layout": case.layout, "condition": case.condition, "simulated": case.simulated,
        "pages": prep_meta, "prep_seconds": round(t_prep, 1),
        "baseline": {"critical_recall": round(token_recall(tokens, btxt), 4),
                     "name_word_recall": round(name_word_recall(case.items, btxt), 4),
                     "items": score_items(base_items, case.items)},
        "prepared": {"critical_recall": round(token_recall(tokens, ptxt), 4),
                     "name_word_recall": round(name_word_recall(case.items, ptxt), 4),
                     "items": score_items(prep_items, case.items)},
    }
    if case.ground_truth_text:
        for side, txt in (("baseline", btxt), ("prepared", ptxt)):
            row[side]["cer"] = round(character_error_rate(case.ground_truth_text, txt), 4)
            row[side]["wer"] = round(word_error_rate(case.ground_truth_text, txt), 4)
    return row


def summarize(rows: List[dict]) -> dict:
    def tot(side, key):
        return sum(r[side]["items"][key] for r in rows)

    by_cond: Dict[str, dict] = {}
    for r in rows:
        c = r["condition"]
        d = by_cond.setdefault(c, {"cases": 0, "lines": 0, "base": 0, "prep": 0, "base_crit": [], "prep_crit": []})
        d["cases"] += 1
        d["lines"] += r["baseline"]["items"]["lines"]
        d["base"] += r["baseline"]["items"]["all_fields"]
        d["prep"] += r["prepared"]["items"]["all_fields"]
        d["base_crit"].append(r["baseline"]["critical_recall"])
        d["prep_crit"].append(r["prepared"]["critical_recall"])
    worse = [r["case"] for r in rows if r["prepared"]["items"]["all_fields"] < r["baseline"]["items"]["all_fields"]]
    return {
        "cases": len(rows),
        "lines": tot("baseline", "lines"),
        "baseline_all_fields": tot("baseline", "all_fields"),
        "prepared_all_fields": tot("prepared", "all_fields"),
        "fields": {k: (tot("baseline", k), tot("prepared", k)) for k in ("name", "quantity", "rate", "amount")},
        "by_condition": {c: {"cases": d["cases"], "lines": d["lines"], "baseline_correct": d["base"],
                             "prepared_correct": d["prep"],
                             "baseline_critical_recall": round(float(np.mean(d["base_crit"])), 3),
                             "prepared_critical_recall": round(float(np.mean(d["prep_crit"])), 3)}
                         for c, d in by_cond.items()},
        "cases_worse_after_preparation": worse,
    }


def to_markdown(rows: List[dict], summary: dict, simulated: bool) -> str:
    lines = []
    if simulated:
        lines.append("> **Simulated camera captures** of the repository's invoice layouts (not real photographs). "
                     "See `tests/real_world_validation.py` for the camera model; run it with `--photos` on real photos.\n")
    lines.append(f"Cases: {summary['cases']} · line items: {summary['lines']} · "
                 f"fully correct lines (name+qty+rate+amount): **{summary['baseline_all_fields']} → "
                 f"{summary['prepared_all_fields']}**\n")
    f = summary["fields"]
    lines.append("| Field | Correct today | Correct with preparation |\n|---|---|---|")
    for k, (b, p) in f.items():
        lines.append(f"| {k} | {b} | {p} |")
    lines.append("\n| Condition | Cases | Lines | Correct today | Correct with preparation | Critical-token recall today → prepared |")
    lines.append("|---|---|---|---|---|---|")
    for c, d in summary["by_condition"].items():
        lines.append(f"| {c} | {d['cases']} | {d['lines']} | {d['baseline_correct']} | {d['prepared_correct']} | "
                     f"{d['baseline_critical_recall']:.3f} → {d['prepared_critical_recall']:.3f} |")
    lines.append("\n| Case | Rotation applied | Quality | Version | Lines correct today → prepared | Critical tokens today → prepared |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        rot = ", ".join(str(p["rotation_cw"]) for p in r["pages"])
        q = ", ".join(p["quality"] for p in r["pages"])
        v = ", ".join(p["variant"] for p in r["pages"])
        b, p = r["baseline"], r["prepared"]
        lines.append(f"| {r['case']} | {rot} | {q} | {v} | {b['items']['all_fields']}/{b['items']['lines']} → "
                     f"{p['items']['all_fields']}/{p['items']['lines']} | {b['critical_recall']:.2f} → {p['critical_recall']:.2f} |")
    if summary["cases_worse_after_preparation"]:
        lines.append("\nCases with fewer correct lines after preparation: " + ", ".join(summary["cases_worse_after_preparation"]))
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", type=Path)
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--layouts", nargs="*")
    args = ap.parse_args()
    if args.photos:
        cases = real_photo_cases(args.photos)
    else:
        cases = simulated_cases(args.layouts or SIM_LAYOUTS)
    pipeline = InvoicePipeline(ocr_engine=TesseractOCREngine())
    rows = []
    for case in cases:
        row = run_case(case, pipeline)
        rows.append(row)
        b, p = row["baseline"], row["prepared"]
        print(f"{row['case']:52s} lines {b['items']['all_fields']}/{b['items']['lines']} -> {p['items']['all_fields']}/"
              f"{p['items']['lines']} | critical {b['critical_recall']:.2f} -> {p['critical_recall']:.2f} | "
              f"rot {[x['rotation_cw'] for x in row['pages']]} | {row['prep_seconds']}s", flush=True)
    summary = summarize(rows)
    print(json.dumps({k: v for k, v in summary.items() if k != "by_condition"}, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(to_markdown(rows, summary, simulated=not args.photos), encoding="utf-8")


if __name__ == "__main__":
    main()
