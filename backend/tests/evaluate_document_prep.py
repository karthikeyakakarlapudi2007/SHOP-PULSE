"""
Measured OCR comparison: original photo vs. prepared page, both read by the EXISTING engine.

    cd backend && .venv/bin/python tests/evaluate_document_prep.py [--json out.json] [--md out.md]

For every dataset case:
  baseline  = the photo as uploaded today, through the existing pipeline's own
              AdaptiveImageProcessor + tesseract.js worker (exactly what /invoices/extract does)
  prepared  = the variant recommended by the document preparation layer, through the same path

Metrics against exact ground truth: CER, WER, bag-of-words recall (reading-order independent)
and critical-token recall (decimals, HSN codes, leading-zero numbers).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from doc_prep_dataset import build_dataset  # noqa: E402
from services.document_prep import prepare_page  # noqa: E402
from services.document_prep.ocr_scoring import (  # noqa: E402
    bag_of_words_recall,
    character_error_rate,
    critical_token_recall,
    run_pipeline_ocr,
    word_error_rate,
)


def evaluate(case_ids: List[str] | None = None) -> Dict:
    data = build_dataset()
    rows = []
    for cid, case in data.items():
        if case_ids and cid not in case_ids:
            continue
        base_texts, prep_texts, page_meta = [], [], []
        t_prep = 0.0
        for page in case.pages:
            ok, enc = cv2.imencode(".png", page)
            base_texts.append(run_pipeline_ocr(page).text)
            t = time.perf_counter()
            prepared = prepare_page(enc.tobytes(), "page.png")
            t_prep += time.perf_counter() - t
            variant = prepared.variants[prepared.recommended_variant]
            prep_texts.append(run_pipeline_ocr(variant).text)
            m = prepared.metadata
            page_meta.append({
                "rotation_cw": m["orientation"]["auto_rotation_cw"],
                "skew_deg": m["orientation"]["skew_deg"],
                "perspective": m["document"]["perspective_corrected"],
                "quality_before": m["quality_before"]["grade"],
                "quality_after": m["quality_after"]["grade"],
                "variant": prepared.recommended_variant,
                "enhancement": [s["name"] for s in m["enhancement"].get("steps", [])][1:],
                "retake_recommended": m["retake_recommended"],
            })
        gt = case.ground_truth_text
        base = "\n\n".join(base_texts)
        prep = "\n\n".join(prep_texts)
        row = {
            "case": cid,
            "title": case.title,
            "expected_rotation_cw": case.expected_rotation_cw,
            "pages": page_meta,
            "baseline": {
                "cer": round(character_error_rate(gt, base), 4),
                "wer": round(word_error_rate(gt, base), 4),
                "word_recall": round(bag_of_words_recall(gt, base), 4),
                "critical_recall": round(critical_token_recall(case.critical_tokens, base), 4),
            },
            "prepared": {
                "cer": round(character_error_rate(gt, prep), 4),
                "wer": round(word_error_rate(gt, prep), 4),
                "word_recall": round(bag_of_words_recall(gt, prep), 4),
                "critical_recall": round(critical_token_recall(case.critical_tokens, prep), 4),
            },
            "prep_seconds": round(t_prep, 2),
        }
        rows.append(row)
        b, p = row["baseline"], row["prepared"]
        print(f"{cid:32s} CER {b['cer']:.3f} -> {p['cer']:.3f} | WER {b['wer']:.3f} -> {p['wer']:.3f} | "
              f"words {b['word_recall']:.3f} -> {p['word_recall']:.3f} | critical {b['critical_recall']:.3f} -> "
              f"{p['critical_recall']:.3f} | {[pm['variant'] for pm in page_meta]} {t_prep:.1f}s", flush=True)
    return {"rows": rows}


def to_markdown(result: Dict) -> str:
    lines = [
        "| Case | Rotation (expected → applied) | Quality before → after | Variant | CER before → after | WER before → after | Word recall before → after | Critical tokens before → after |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        rot = ", ".join(str(p["rotation_cw"]) for p in r["pages"])
        q = ", ".join(f"{p['quality_before']} → {p['quality_after']}" for p in r["pages"])
        var = ", ".join(p["variant"] for p in r["pages"])
        b, p = r["baseline"], r["prepared"]
        lines.append(
            f"| {r['title']} | {r['expected_rotation_cw']} → {rot} | {q} | {var} | {b['cer']:.3f} → {p['cer']:.3f} | "
            f"{b['wer']:.3f} → {p['wer']:.3f} | {b['word_recall']:.3f} → {p['word_recall']:.3f} | "
            f"{b['critical_recall']:.3f} → {p['critical_recall']:.3f} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("cases", nargs="*")
    args = ap.parse_args()
    res = evaluate(args.cases or None)
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2), encoding="utf-8")
    if args.md:
        Path(args.md).write_text(to_markdown(res), encoding="utf-8")
