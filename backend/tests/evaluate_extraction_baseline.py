"""
Field-level extraction baseline through the SAME code path as POST /api/v1/invoices/extract
(services.invoice._extract_invoice_with_new_pipeline), on the datasets that exist in the repository.
Each dataset is reported on its own; results are never combined, and none of them is real-world
evidence (see validation/real_invoices for that).

Datasets
  fixtures   tests/fixtures/ground_truth (32 repository invoice files: PDFs, renders, one
             noisy photo-like render), uploaded as-is.
  simulated  the 81 simulated phone captures of tests/real_world_validation.py (10 layouts x 8
             conditions + a two-page case), prepared by document_prep and sent as the PDF the app
             uploads.
  synthetic  the 17 synthetic pages of tests/doc_prep_dataset.py (exact header and items),
             prepared and sent as a PDF.

Prepared PDFs are deterministic and cached in --cache, so before/after runs of the extraction code
compare the same inputs. Delete the cache when image preparation itself changes.

    cd backend && .venv/bin/python tests/evaluate_extraction_baseline.py --cache /tmp/x \
        --json out.json --md out.md [--datasets fixtures simulated synthetic]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from services import mrp_lookup  # noqa: E402
from services.invoice import _extract_invoice_with_new_pipeline  # noqa: E402
from validation_scoring import _match_items, merge_field_counts, score_header, score_items  # noqa: E402

FIXTURES = HERE / "fixtures" / "ground_truth"
FIN = ("quantity", "purchase_price", "printed_amount")


class _NoProducts:
    """Stand-in session: the shop has no products yet (no inventory matching)."""

    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return []


# --------------------------------------------------------------------------------------- inputs


def fixture_inputs() -> List[dict]:
    """Repository fixtures, scored against the values verified as printed (printed_values.json)."""
    pv = json.loads((FIXTURES / "printed_values.json").read_text(encoding="utf-8"))["cases"]
    gt = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    out = []
    for key, e in pv.items():
        out.append({"case": key, "file": str(FIXTURES / "invoices" / e["filename"]), "name": e["filename"],
                    "items": e["items"], "header": e["header"], "layout": gt[key]["layout_type"]})
    return out


def _prepared_pdf(pages: List[bytes], dest: Path) -> Dict[str, Any]:
    from services.document_prep import prepare_page
    from services.document_prep.pdf_builder import build_pdf

    meta_path = dest.with_suffix(".json")
    if dest.is_file() and meta_path.is_file():
        return json.loads(meta_path.read_text())
    imgs, meta, t = [], [], time.perf_counter()
    for i, data in enumerate(pages):
        p = prepare_page(data, f"photo{i}.jpg")
        imgs.append(p.variants[p.recommended_variant])
        meta.append({"rotation_cw": p.metadata["orientation"]["auto_rotation_cw"],
                     "retake": p.metadata["retake_recommended"], "variant": p.recommended_variant})
    dest.write_bytes(build_pdf(imgs).data)
    info = {"pages": meta, "prep_seconds": round(time.perf_counter() - t, 2)}
    meta_path.write_text(json.dumps(info))
    return info


def simulated_inputs(cache: Path) -> List[dict]:
    from real_world_validation import simulated_cases

    pv = json.loads((FIXTURES / "printed_values.json").read_text(encoding="utf-8"))["cases"]
    out = []
    d = cache / "simulated"
    d.mkdir(parents=True, exist_ok=True)
    for c in simulated_cases():
        pdf = d / f"{c.case_id}.pdf"
        info = _prepared_pdf(c.pages, pdf)
        # score against the values printed on the photographed page (not ground_truth.json)
        items, header = (pv[c.layout]["items"], pv[c.layout]["header"]) if c.layout in pv else (c.items, None)
        out.append({"case": c.case_id, "file": str(pdf), "name": "scan.pdf", "items": items, "header": header,
                    "layout": c.layout, "condition": c.condition, "prep": info})
        print(f"  prepared {c.case_id}", flush=True)
    return out


def synthetic_inputs(cache: Path) -> List[dict]:
    from doc_prep_dataset import PAGE_1_ITEMS, PAGE_2_ITEMS, build_dataset

    def items(rows):
        return [{"product_name": r[1], "quantity": float(r[3]), "unit": r[4], "purchase_price": float(r[5]),
                 "mrp": float(r[6]), "printed_amount": float(r[7])} for r in rows]

    out = []
    d = cache / "synthetic"
    d.mkdir(parents=True, exist_ok=True)
    for cid, c in build_dataset().items():
        pages = [cv2.imencode(".jpg", p, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes() for p in c.pages]
        pdf = d / f"{cid}.pdf"
        info = _prepared_pdf(pages, pdf)
        rows = PAGE_1_ITEMS + PAGE_2_ITEMS if len(c.pages) == 2 else (
            PAGE_1_ITEMS[:5] if cid == "02_landscape" else PAGE_1_ITEMS)
        inv = {"02_landscape": "INV-00511"}.get(cid, "INV-00427")
        out.append({"case": cid, "file": str(pdf), "name": "scan.pdf", "items": items(rows),
                    "header": {"supplier_name": "Sri Lakshmi Wholesale Traders", "invoice_number": inv,
                               "invoice_date": "08/10/2026"},
                    "layout": "bordered table", "condition": c.title, "prep": info})
        print(f"  prepared {cid}", flush=True)
    return out


# --------------------------------------------------------------------------------------- run


def extract(path: str, name: str) -> Dict[str, Any]:
    data = Path(path).read_bytes()
    t = time.perf_counter()
    try:
        r = _extract_invoice_with_new_pipeline(data, name, _NoProducts(), uuid.uuid4())
    except Exception as exc:  # a failed extraction is a result, never hidden
        return {"error": f"{type(exc).__name__}: {exc}", "items": [], "header": {}, "seconds": time.perf_counter() - t}
    items = [{
        "product_name": i.product_name, "quantity": i.quantity, "unit": i.unit, "purchase_price": i.purchase_price,
        "mrp": i.invoice_mrp, "printed_amount": i.printed_amount, "line_total": i.line_total,
        "needs_review": i.needs_review, "arithmetic_status": i.arithmetic_status, "suggestions": i.suggestions,
        "suggested_rate": i.suggested_rate, "source_text": i.source_text, "raw_cells": i.raw_cells,
        "pack_size": i.pack_size, "pack_size_unit": i.pack_size_unit,
    } for i in r.items]
    return {"items": items, "status": r.status, "seconds": round(time.perf_counter() - t, 2),
            "header": {"supplier_name": r.supplier_name, "invoice_number": r.invoice_number,
                       "invoice_date": r.invoice_date},
            "columns": r.diagnostics.detected_columns if r.diagnostics else [],
            "raw_text": r.raw_ocr_text}


def _canonical_units(items: List[dict]) -> List[dict]:
    """Units are compared in the product's own canonical vocabulary (btl = PET, KGS = KG, pack = PKT);
    this is naming, never a conversion of quantities."""
    from services.grocery_ocr.extraction.unit_normalizer import UnitNormalizer

    un = UnitNormalizer()
    out = []
    for it in items:
        u = it.get("unit")
        out.append(dict(it, unit=(un.normalize(u).normalized_unit or u) if u else u))
    return out


def review_safety(extracted: List[dict], truth: List[dict]) -> Dict[str, int]:
    """How wrong quantity / rate / amount values reach the user: flagged for review or silently."""
    out = {"wrong_lines": 0, "wrong_flagged": 0, "wrong_silent": 0, "extra_lines": 0, "extra_flagged": 0}
    pairs = _match_items(extracted, truth)
    matched = {e for _, e in pairs if e is not None}
    for ti, ei in pairs:
        if ei is None:
            continue
        t, e = truth[ti], extracted[ei]
        amb = set(t.get("ambiguous") or [])
        wrong = any(f not in amb and t.get(f) is not None and
                    (e.get(f) is None or abs(float(e[f]) - float(t[f])) >= 0.011) for f in FIN)
        if wrong:
            out["wrong_lines"] += 1
            out["wrong_flagged" if e.get("needs_review") else "wrong_silent"] += 1
    for i, e in enumerate(extracted):
        if i not in matched:
            out["extra_lines"] += 1
            out["extra_flagged"] += int(bool(e.get("needs_review")))
    return out


def evaluate(inputs: List[dict], previous: Optional[Dict[str, dict]] = None) -> List[dict]:
    """Extract and score every input; with `previous` (case -> saved row), re-score saved results only."""
    rows = []
    for inp in inputs:
        res = previous[inp["case"]]["result"] if previous is not None else extract(inp["file"], inp["name"])
        row = {k: v for k, v in inp.items() if k not in ("file",)}
        row["result"] = res
        row["score"] = score_items(_canonical_units(res["items"]), _canonical_units(inp["items"])) if inp["items"] else None
        row["safety"] = review_safety(res["items"], inp["items"])
        row["header_score"] = score_header(res["header"], inp["header"])
        rows.append(row)
        s = row["score"]
        print(f"  {inp['case']:44s} full {s['fully_correct'] if s else '-'}/{len(inp['items'])} "
              f"silent-wrong {row['safety']['wrong_silent']} extra {row['safety']['extra_lines']} "
              f"hdr {row['header_score']} {res.get('error') or ''}", flush=True)
    return rows


def summarize(rows: List[dict]) -> Dict[str, Any]:
    scored = [r["score"] for r in rows if r["score"]]
    hdr: Dict[str, Dict[str, int]] = {}
    for r in rows:
        for f, v in r["header_score"].items():
            hdr.setdefault(f, {}).setdefault(v, 0)
            hdr[f][v] += 1
    safety = {k: sum(r["safety"][k] for r in rows) for k in rows[0]["safety"]} if rows else {}
    dec = [dict(d, case=r["case"]) for r in rows if r["score"] for d in r["score"]["decimal_corruption"]]
    return {
        "cases": len(rows),
        "errors": [(r["case"], r["result"]["error"]) for r in rows if r["result"].get("error")],
        "lines": sum(s["lines"] for s in scored),
        "lines_found": sum(s["lines_found"] for s in scored),
        "fully_correct": sum(s["fully_correct"] for s in scored),
        "partially_correct": sum(s["partially_correct"] for s in scored),
        "fields": merge_field_counts(scored),
        "decimal_corruption": dec,
        "review_safety": safety,
        "header": hdr,
        "extraction_seconds_median": sorted(r["result"]["seconds"] for r in rows)[len(rows) // 2] if rows else None,
    }


def to_markdown(results: Dict[str, Dict[str, Any]]) -> str:
    out = ["# Extraction baseline (repository datasets — NOT real-world evidence)", ""]
    for ds, res in results.items():
        s = res["summary"]
        out += [f"## {ds}", "", f"Cases {s['cases']} · line items {s['lines']} · found {s['lines_found']} · "
                f"fully correct {s['fully_correct']} · partially correct {s['partially_correct']} · "
                f"errors {len(s['errors'])}", "", "| Field | Evaluated | Correct | Invented |", "|---|---|---|---|"]
        for f, c in s["fields"].items():
            out.append(f"| {f} | {c['evaluated']} | {c['correct']} | {c['invented']} |")
        rs = s["review_safety"]
        out += ["", f"Wrong qty/rate/amount on {rs['wrong_lines']} found lines: flagged {rs['wrong_flagged']}, "
                f"**silent {rs['wrong_silent']}**. Extra (non-invoice) lines {rs['extra_lines']}, flagged "
                f"{rs['extra_flagged']}.", "", f"Decimal corruption: {len(s['decimal_corruption'])}"]
        for d in s["decimal_corruption"]:
            out.append(f"- {d['case']}: {d['product']} {d['field']} {d['expected']} -> {d['got']} ({d['kind']})")
        out += ["", "| Header field | " + " | ".join(sorted({k for v in s['header'].values() for k in v})) + " |"]
        keys = sorted({k for v in s["header"].values() for k in v})
        out.append("|---" * (len(keys) + 1) + "|")
        for f, v in s["header"].items():
            out.append(f"| {f} | " + " | ".join(str(v.get(k, 0)) for k in keys) + " |")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--datasets", nargs="*", default=["fixtures", "simulated", "synthetic"])
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    ap.add_argument("--rescore", type=Path, help="re-score the extraction results saved in this JSON (no OCR)")
    args = ap.parse_args()
    saved = json.loads(args.rescore.read_text(encoding="utf-8")) if args.rescore else None
    mrp_lookup.get_provider = lambda: mrp_lookup.NoProvider()  # offline: MRP only as printed
    builders = {"fixtures": lambda: fixture_inputs(), "simulated": lambda: simulated_inputs(args.cache),
                "synthetic": lambda: synthetic_inputs(args.cache)}
    results = {}
    for ds in (args.datasets if saved is None else [d for d in args.datasets if d in saved]):
        print(f"[{ds}]", flush=True)
        prev = {r["case"]: r for r in saved[ds]["rows"]} if saved is not None else None
        rows = evaluate(builders[ds](), prev)
        results[ds] = {"summary": summarize(rows), "rows": rows}
        print(json.dumps({k: v for k, v in results[ds]["summary"].items() if k != "decimal_corruption"}), flush=True)
    if args.json:
        args.json.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    if args.md:
        args.md.write_text(to_markdown(results), encoding="utf-8")


if __name__ == "__main__":
    main()
