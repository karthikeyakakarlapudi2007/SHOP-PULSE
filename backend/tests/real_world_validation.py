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
       python tests/real_world_validation.py --photos ../validation/real_invoices --check   # manifest only
       python tests/real_world_validation.py --photos ../validation/real_invoices --md OUT.md --json OUT.json
   The folder holds the photos and a manifest.json (schema in tests/validation_scoring.py; template
   and capture requirements in validation/real_invoices/). Every case declares its provenance;
   results are reported per provenance category (actual photographs, scans, screenshots,
   fixtures, simulated) and never combined into one number.

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
    run_pipeline_ocr,
    word_error_rate,
)
from services.document_prep.pdf_builder import build_pdf  # noqa: E402
from services.grocery_ocr.engines.ocr_engine import TesseractOCREngine  # noqa: E402
from services.grocery_ocr.pipeline.invoice_pipeline import InvoicePipeline  # noqa: E402
from validation_scoring import (  # noqa: E402
    SOURCES,
    merge_field_counts,
    read_manifest,
    score_header,
    score_items,
    validate_manifest,
)

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
    source: str = "simulated"  # provenance category; results are never merged across categories
    header: Optional[dict] = None  # expected supplier / invoice number / date (null = not printed)
    language: str = "en"
    conditions: List[str] = field(default_factory=list)
    filenames: List[str] = field(default_factory=list)


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


def _fixture_header(entry: dict) -> dict:
    """Header values recorded in the fixture ground truth (fields it does not record are omitted)."""
    return {k: entry[k] for k in ("supplier_name", "invoice_number", "invoice_date") if k in entry}


def simulated_cases(layouts: Sequence[str] = SIM_LAYOUTS, conditions: Sequence[str] = SIM_CONDITIONS) -> List[Case]:
    gt = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    cases: List[Case] = []
    for li, key in enumerate(layouts):
        page = cv2.imread(str(FIXTURES / "invoices" / gt[key]["filename"]), cv2.IMREAD_COLOR)
        for ci, cond in enumerate(conditions):
            cases.append(Case(f"{key}__{cond}", key, cond, [photograph(page, cond, 1000 + li * 37 + ci)],
                              gt[key]["items"], header=_fixture_header(gt[key])))
    # Multi-page: two different invoices photographed as one document, second page sideways
    p1 = cv2.imread(str(FIXTURES / "invoices" / gt["TC24_dairy_and_staples"]["filename"]), cv2.IMREAD_COLOR)
    p2 = cv2.imread(str(FIXTURES / "invoices" / gt["TC29_flours_and_pulses"]["filename"]), cv2.IMREAD_COLOR)
    cases.append(Case("multi_page__TC24+TC29", "TC24 + TC29", "multi_page (page 2 sideways)",
                      [photograph(p1, "tilted", 77), photograph(p2, "sideways", 78)],
                      gt["TC24_dairy_and_staples"]["items"] + gt["TC29_flours_and_pulses"]["items"]))
    return cases


def load_photo_folder(folder: Path) -> Tuple[List["Case"], List[str]]:
    """Read and validate <folder>/manifest.json. Returns (cases, problems)."""
    mf = folder / "manifest.json"
    if not mf.is_file():
        return [], [f"{mf} not found (copy validation/real_invoices/manifest.template.json and fill it in)"]
    raw = json.loads(mf.read_text(encoding="utf-8"))
    problems = validate_manifest(raw, folder)
    cases = []
    for cid, entry in read_manifest(raw).items():
        prov = entry.get("provenance") or {}
        files = entry.get("files") or []
        if any(not (folder / f).is_file() for f in files):
            continue
        cases.append(Case(
            cid, entry.get("layout", "unspecified"), ", ".join(entry.get("conditions") or []) or entry.get("condition", ""),
            [(folder / f).read_bytes() for f in files], entry.get("items") or [],
            entry.get("ground_truth_text"), entry.get("critical_tokens", []),
            simulated=prov.get("source") == "simulated", source=prov.get("source", "unknown"),
            header=entry.get("header"), language=entry.get("language", "en"),
            conditions=list(entry.get("conditions") or []), filenames=list(files)))
    return cases, problems


def real_photo_cases(folder: Path) -> List["Case"]:
    cases, problems = load_photo_folder(folder)
    if problems:
        raise SystemExit("Manifest problems - fix them before running:\n  " + "\n  ".join(problems))
    return cases


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


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


def _item_dicts(items) -> List[dict]:
    out = []
    for i in items:
        out.append({
            "product_name": i.normalized_product_name or i.raw_product_name,
            "quantity": float(i.quantity) if i.quantity is not None else None,
            "unit": i.unit,
            "purchase_price": float(i.purchase_price) if i.purchase_price is not None else None,
            "mrp": float(i.mrp) if i.mrp is not None else None,
            "printed_amount": float(i.printed_amount) if i.printed_amount is not None else None,
        })
    return out


def _extract(pipeline: InvoicePipeline, data: bytes, name: str) -> Tuple[List[dict], dict, float, Optional[str]]:
    t = time.perf_counter()
    try:
        res = pipeline.process(data, name)
        header = {"supplier_name": res.supplier_name, "invoice_number": res.invoice_number,
                  "invoice_date": res.invoice_date}
        return _item_dicts(res.items), header, time.perf_counter() - t, None
    except Exception as exc:  # recorded as a failed extraction, never hidden
        return [], {}, time.perf_counter() - t, f"{type(exc).__name__}: {exc}"


def _peak_memory_mb() -> Dict[str, float]:
    try:
        import resource

        own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        kids = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024.0
        return {"python_peak_mb": round(own, 1), "ocr_worker_peak_mb": round(kids, 1)}
    except Exception:
        return {}


def run_case(case: Case, pipeline: InvoicePipeline) -> dict:
    """Original photos vs prepared pages, read by the same existing extraction pipeline.

    Today a single photo is uploaded as-is; several photos cannot be sent as one invoice, so for
    multi-page cases each original page is extracted on its own and the line items combined.
    """
    base_text, base_items, base_header, base_errors = [], [], {}, []
    prep_text, prep_imgs, prep_meta = [], [], []
    t_base = t_prep = 0.0
    for i, data in enumerate(case.pages):
        photo = cv2.cvtColor(load_image(data, f"p{i}.jpg").rgb, cv2.COLOR_RGB2BGR)
        base_text.append(run_pipeline_ocr(photo).text)
        items, header, secs, err = _extract(pipeline, data, case.filenames[i] if i < len(case.filenames) else f"photo{i}.jpg")
        t_base += secs
        base_items += items
        if i == 0:
            base_header = header
        if err:
            base_errors.append(err)
        t = time.perf_counter()
        prepared = prepare_page(data, f"photo{i}.jpg")
        page_secs = time.perf_counter() - t
        t_prep += page_secs
        variant = prepared.variants[prepared.recommended_variant]
        prep_imgs.append(variant)
        prep_text.append(run_pipeline_ocr(variant).text)
        md = prepared.metadata
        prep_meta.append({
            "rotation_cw": md["orientation"]["auto_rotation_cw"],
            "orientation_confidence": md["orientation"]["confidence"],
            "skew_deg": md["orientation"]["skew_deg"],
            "perspective": md["document"]["perspective_corrected"],
            "quality": f"{md['quality_before']['grade']} -> {md['quality_after']['grade']}",
            "variant": prepared.recommended_variant,
            "enhancement": [st["name"] for st in md["enhancement"].get("steps", [])][1:],
            "retake": md["retake_recommended"],
            "prep_seconds": round(page_secs, 2),
        })
    pdf = build_pdf(prep_imgs)
    prep_items, prep_header, t_prep_extract, prep_error = _extract(pipeline, pdf.data, "scan.pdf")
    btxt, ptxt = "\n\n".join(base_text), "\n\n".join(prep_text)
    tokens = critical_tokens(case.items, case.extra_tokens)
    row = {
        "case": case.case_id, "source": case.source, "layout": case.layout, "condition": case.condition,
        "conditions": case.conditions, "language": case.language, "simulated": case.simulated,
        "page_count": len(case.pages), "pages": prep_meta,
        "timing_s": {"original_extraction": round(t_base, 2), "preparation": round(t_prep, 2),
                     "prepared_extraction": round(t_prep_extract, 2)},
        "pdf": {"bytes": len(pdf.data), "pages": [vars(p) for p in pdf.pages]},
        "memory": _peak_memory_mb(),
        "baseline": {"critical_recall": round(token_recall(tokens, btxt), 4),
                     "name_word_recall": round(name_word_recall(case.items, btxt), 4),
                     "items": score_items(base_items, case.items),
                     "header": score_header(base_header, case.header),
                     "errors": base_errors},
        "prepared": {"critical_recall": round(token_recall(tokens, ptxt), 4),
                     "name_word_recall": round(name_word_recall(case.items, ptxt), 4),
                     "items": score_items(prep_items, case.items),
                     "header": score_header(prep_header, case.header),
                     "errors": [prep_error] if prep_error else []},
    }
    if case.ground_truth_text:
        for side, txt in (("baseline", btxt), ("prepared", ptxt)):
            row[side]["cer"] = round(character_error_rate(case.ground_truth_text, txt), 4)
            row[side]["wer"] = round(word_error_rate(case.ground_truth_text, txt), 4)
    row["prepared_worse"] = row["prepared"]["items"]["fully_correct"] < row["baseline"]["items"]["fully_correct"]
    return row


def summarize(rows: List[dict]) -> dict:
    """Totals per provenance category (never one combined number across categories)."""
    out: Dict[str, dict] = {}
    for source in sorted({r["source"] for r in rows}):
        rs = [r for r in rows if r["source"] == source]

        def tot(side, key):
            return sum(r[side]["items"][key] for r in rs)

        def header_counts(side):
            counts: Dict[str, Dict[str, int]] = {}
            for r in rs:
                for f, v in r[side]["header"].items():
                    counts.setdefault(f, {}).setdefault(v, 0)
                    counts[f][v] += 1
            return counts

        def mean(side, key):
            vals = [r[side][key] for r in rs if key in r[side]]
            return round(float(np.mean(vals)), 4) if vals else None

        by_cond: Dict[str, dict] = {}
        for r in rs:
            for c in (r["conditions"] or [r["condition"]]):
                d = by_cond.setdefault(c, {"cases": 0, "lines": 0, "baseline_correct": 0, "prepared_correct": 0})
                d["cases"] += 1
                d["lines"] += r["baseline"]["items"]["lines"]
                d["baseline_correct"] += r["baseline"]["items"]["fully_correct"]
                d["prepared_correct"] += r["prepared"]["items"]["fully_correct"]
        out[source] = {
            "label": SOURCES.get(source, source),
            "cases": len(rs),
            "pages": sum(r["page_count"] for r in rs),
            "layouts": len({r["layout"] for r in rs}),
            "languages": sorted({r["language"] for r in rs}),
            "lines": tot("baseline", "lines"),
            "fully_correct": {"baseline": tot("baseline", "fully_correct"), "prepared": tot("prepared", "fully_correct")},
            "partially_correct": {"baseline": tot("baseline", "partially_correct"),
                                  "prepared": tot("prepared", "partially_correct")},
            "fields": {"baseline": merge_field_counts(r["baseline"]["items"] for r in rs),
                       "prepared": merge_field_counts(r["prepared"]["items"] for r in rs)},
            "header": {"baseline": header_counts("baseline"), "prepared": header_counts("prepared")},
            "cer": {"baseline": mean("baseline", "cer"), "prepared": mean("prepared", "cer")},
            "wer": {"baseline": mean("baseline", "wer"), "prepared": mean("prepared", "wer")},
            "critical_recall": {"baseline": mean("baseline", "critical_recall"),
                                "prepared": mean("prepared", "critical_recall")},
            "decimal_corruption": {"baseline": sum(len(r["baseline"]["items"]["decimal_corruption"]) for r in rs),
                                   "prepared": sum(len(r["prepared"]["items"]["decimal_corruption"]) for r in rs)},
            "prepared_worse_cases": [r["case"] for r in rs if r["prepared_worse"]],
            "retake_recommended": sum(1 for r in rs if any(p["retake"] for p in r["pages"])),
            "timing_s_per_page": {
                "preparation_median": round(float(np.median([p["prep_seconds"] for r in rs for p in r["pages"]])), 2),
                "preparation_max": round(float(np.max([p["prep_seconds"] for r in rs for p in r["pages"]])), 2),
            },
            "pdf_bytes_per_page_median": int(np.median([r["pdf"]["bytes"] / r["page_count"] for r in rs])),
            "by_condition": by_cond,
        }
    return out


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100.0 * n / d:.0f}%)" if d else "n/a"


def to_markdown(rows: List[dict], summary: dict, simulated: bool) -> str:
    lines: List[str] = []
    for source, s in summary.items():
        lines.append(f"## {s['label']} ({source})\n")
        if source != "real_photo":
            lines.append(f"> Not real-world evidence: {s['label'].lower()} results are reported separately and must not "
                         "be combined with actual-photograph results.\n")
        lines.append(f"Cases {s['cases']} · pages {s['pages']} · layouts {s['layouts']} · languages "
                     f"{', '.join(s['languages'])} · line items {s['lines']}\n")
        lines.append("| Measure | Original photo | Prepared page |\n|---|---|---|")
        lines.append(f"| Fully correct lines (name+qty+rate+amount) | {_pct(s['fully_correct']['baseline'], s['lines'])} | "
                     f"{_pct(s['fully_correct']['prepared'], s['lines'])} |")
        lines.append(f"| Partially correct lines | {s['partially_correct']['baseline']} | {s['partially_correct']['prepared']} |")
        for f in ("product_name", "quantity", "unit", "purchase_price", "mrp", "printed_amount"):
            b, p = s["fields"]["baseline"].get(f), s["fields"]["prepared"].get(f)
            if b and b["evaluated"]:
                lines.append(f"| {f} correct | {_pct(b['correct'], b['evaluated'])} | {_pct(p['correct'], p['evaluated'])} |")
            if b and (b["invented"] or p["invented"]):
                lines.append(f"| {f} INVENTED (not printed) | {b['invented']} | {p['invented']} |")
        for f in ("supplier_name", "invoice_number", "invoice_date"):
            b, p = s["header"]["baseline"].get(f, {}), s["header"]["prepared"].get(f, {})
            if set(b) - {"not_recorded"}:
                fmt = lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items()))  # noqa: E731
                lines.append(f"| {f} | {fmt(b)} | {fmt(p)} |")
        for key, label in (("cer", "CER (lower is better)"), ("wer", "WER (lower is better)"),
                           ("critical_recall", "Critical-token recall")):
            if s[key]["baseline"] is not None:
                lines.append(f"| {label} | {s[key]['baseline']:.3f} | {s[key]['prepared']:.3f} |")
        lines.append(f"| Decimal-point corruptions (e.g. 58.75 -> 58575) | {s['decimal_corruption']['baseline']} | "
                     f"{s['decimal_corruption']['prepared']} |")
        lines.append(f"\nPreparation time per page: median {s['timing_s_per_page']['preparation_median']} s, "
                     f"max {s['timing_s_per_page']['preparation_max']} s · median PDF size per page "
                     f"{s['pdf_bytes_per_page_median'] / 1e6:.2f} MB · retake advised on {s['retake_recommended']} case(s)\n")
        if s["prepared_worse_cases"]:
            lines.append("Cases with fewer fully correct lines after preparation (the 'read original photos' fallback "
                         "would give the original result): " + ", ".join(s["prepared_worse_cases"]) + "\n")
        lines.append("| Condition | Cases | Lines | Correct original | Correct prepared |\n|---|---|---|---|---|")
        for c, d in sorted(s["by_condition"].items()):
            lines.append(f"| {c} | {d['cases']} | {d['lines']} | {d['baseline_correct']} | {d['prepared_correct']} |")
        lines.append("")
        lines.append("| Case | Pages | Rotation | Quality | Version | Full lines orig -> prep | Critical tokens | Decimal issues |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in [r for r in rows if r["source"] == source]:
            b, p = r["baseline"], r["prepared"]
            lines.append(
                f"| {r['case']} | {r['page_count']} | {', '.join(str(x['rotation_cw']) for x in r['pages'])} | "
                f"{', '.join(x['quality'] for x in r['pages'])} | {', '.join(x['variant'] for x in r['pages'])} | "
                f"{b['items']['fully_correct']}/{b['items']['lines']} -> {p['items']['fully_correct']}/{p['items']['lines']} | "
                f"{b['critical_recall']:.2f} -> {p['critical_recall']:.2f} | "
                f"{len(b['items']['decimal_corruption'])} -> {len(p['items']['decimal_corruption'])} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--photos", type=Path, help="folder with photos and manifest.json")
    ap.add_argument("--check", action="store_true", help="only validate the manifest and images (no OCR)")
    ap.add_argument("--md")
    ap.add_argument("--json")
    ap.add_argument("--layouts", nargs="*")
    args = ap.parse_args()
    if args.check:
        if not args.photos:
            raise SystemExit("--check needs --photos DIR")
        cases, problems = load_photo_folder(args.photos)
        for c in cases:
            for i, data in enumerate(c.pages):
                try:
                    load_image(data, c.filenames[i])
                except Exception as exc:
                    problems.append(f"{c.case_id}: page {i + 1} cannot be read ({exc})")
        by_source: Dict[str, int] = {}
        for c in cases:
            by_source[c.source] = by_source.get(c.source, 0) + 1
        print(f"cases readable: {len(cases)} {by_source} · pages {sum(len(c.pages) for c in cases)} · "
              f"line items {sum(len(c.items) for c in cases)}")
        print("problems:\n  " + "\n  ".join(problems) if problems else "manifest OK")
        raise SystemExit(1 if problems else 0)
    cases = real_photo_cases(args.photos) if args.photos else simulated_cases(args.layouts or SIM_LAYOUTS)
    pipeline = InvoicePipeline(ocr_engine=TesseractOCREngine())
    rows = []
    for case in cases:
        row = run_case(case, pipeline)
        rows.append(row)
        b, p = row["baseline"], row["prepared"]
        print(f"[{row['source']}] {row['case']:48s} full lines {b['items']['fully_correct']}/{b['items']['lines']} -> "
              f"{p['items']['fully_correct']}/{p['items']['lines']} | critical {b['critical_recall']:.2f} -> "
              f"{p['critical_recall']:.2f} | rot {[x['rotation_cw'] for x in row['pages']]} | "
              f"prep {row['timing_s']['preparation']}s", flush=True)
    summary = summarize(rows)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("by_condition", "fields", "header")}
                      for k, v in summary.items()}, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str),
                                   encoding="utf-8")
    if args.md:
        Path(args.md).write_text(to_markdown(rows, summary, simulated=not args.photos), encoding="utf-8")


if __name__ == "__main__":
    main()
