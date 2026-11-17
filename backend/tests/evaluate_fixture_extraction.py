"""
Extraction-level comparison on the repository's real invoice fixtures (ground_truth.json).

For every image fixture, and for sideways / upside-down copies of a few of them:
  baseline  = the image uploaded as today -> existing InvoicePipeline (unchanged)
  prepared  = document preparation -> PDF -> the same InvoicePipeline
A line counts as correct only if product name, quantity, rate and printed amount all match.

    cd backend && .venv/bin/python tests/evaluate_fixture_extraction.py [--md out.md]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from services.document_prep import prepare_page  # noqa: E402
from services.document_prep.pdf_builder import build_pdf  # noqa: E402
from services.grocery_ocr.engines.ocr_engine import TesseractOCREngine  # noqa: E402
from services.grocery_ocr.pipeline.invoice_pipeline import InvoicePipeline  # noqa: E402

FIXTURES = HERE / "fixtures" / "ground_truth"
DOCS = HERE.parent.parent / "docs" / "scanner-test-cases"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def score(items, truth) -> int:
    got = []
    for it in items:
        got.append((norm(it.normalized_product_name or it.raw_product_name), it.quantity, it.purchase_price,
                    it.printed_amount))
    correct = 0
    for t in truth:
        tn = norm(t["product_name"])
        for name, q, p, a in got:
            if not name or not (tn in name or name in tn):
                continue
            ok = (q is not None and abs(float(q) - t["quantity"]) < 1e-6
                  and p is not None and abs(float(p) - t["purchase_price"]) < 0.011
                  and (t.get("printed_amount") is None or (a is not None and abs(float(a) - t["printed_amount"]) < 0.011)))
            if ok:
                correct += 1
                break
    return correct


def extract(pipeline, data: bytes, name: str):
    try:
        res = pipeline.process(data, name)
        return res.items
    except Exception as exc:  # report, do not crash the evaluation
        print(f"   extraction error for {name}: {type(exc).__name__}: {exc}")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    args = ap.parse_args()
    gt = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    pipeline = InvoicePipeline(ocr_engine=TesseractOCREngine())
    rows = []
    jobs = []
    for key, entry in gt.items():
        fn = entry["filename"]
        if not fn.lower().endswith((".png", ".jpg", ".jpeg")) or not entry.get("items"):
            continue
        path = FIXTURES / "invoices" / fn
        if not path.exists():
            alt = DOCS / fn.replace("_", "-", 1).replace("_", "-")
            path = alt if alt.exists() else None
        if path is None:
            continue
        jobs.append((key, path, 0))
        if key in ("TC13_sri_balaji_13items", "TC15_decimal_quantities", "TC03_phone_photo"):
            jobs += [(key, path, 90), (key, path, 180)]
    for key, path, rot in jobs:
        truth = gt[key]["items"]
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if rot:
            img = cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180}[rot])
        ok, enc = cv2.imencode(".png", img)
        original = enc.tobytes() if rot else path.read_bytes()
        base_items = extract(pipeline, original, path.name if not rot else "photo.png")
        prepared = prepare_page(original, path.name)
        variant = prepared.variants[prepared.recommended_variant]
        pdf = build_pdf([variant]).data
        prep_items = extract(pipeline, pdf, "scan.pdf")
        b, p = score(base_items, truth), score(prep_items, truth)
        md = prepared.metadata
        row = {
            "case": f"{key}" + (f" (photo turned {rot} deg)" if rot else ""),
            "lines": len(truth),
            "baseline_correct": b,
            "prepared_correct": p,
            "quality": f"{md['quality_before']['grade']} -> {md['quality_after']['grade']}",
            "rotation": md["orientation"]["auto_rotation_cw"],
            "skew": md["orientation"]["skew_deg"],
            "variant": prepared.recommended_variant,
        }
        rows.append(row)
        print(f"{row['case']:48s} correct lines {b}/{len(truth)} -> {p}/{len(truth)} | rot {row['rotation']} skew {row['skew']} "
              f"| {row['quality']} | {row['variant']}", flush=True)
    tb = sum(r["baseline_correct"] for r in rows)
    tp = sum(r["prepared_correct"] for r in rows)
    tl = sum(r["lines"] for r in rows)
    print(f"TOTAL correct lines: {tb}/{tl} -> {tp}/{tl}")
    if args.md:
        out = ["| Fixture | Lines | Correct today | Correct with preparation | Rotation applied | Tilt (deg) | Quality before -> after | Version |",
               "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| {r['case']} | {r['lines']} | {r['baseline_correct']} | {r['prepared_correct']} | {r['rotation']} | "
                       f"{r['skew']} | {r['quality']} | {r['variant']} |")
        out.append(f"| **Total** | **{tl}** | **{tb}** | **{tp}** | | | | |")
        Path(args.md).write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
