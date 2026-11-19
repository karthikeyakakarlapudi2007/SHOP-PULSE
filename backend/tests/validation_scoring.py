"""
Manifest validation and scoring for invoice-scanner validation runs.

Pure functions (no OCR), shared by tests/real_world_validation.py and its unit tests.

Manifest (schema_version 2; the older {case_id: {...}} form is still read):

{
  "schema_version": 2,
  "cases": {
    "inv01": {
      "provenance": {"source": "real_photo", "device": "Redmi Note 12", "captured_on": "2026-11-20",
                     "captured_by": "shop owner", "anonymized": true},
      "files": ["inv01_p1.jpg", "inv01_p2.jpg"],          # page order
      "conditions": ["low_light", "rotated_90"],
      "layout": "Wholesale bill, bordered table",
      "language": "en",
      "header": {"supplier_name": "...", "invoice_number": "...", "invoice_date": "08/10/2026"},
      "items": [{"product_name": "...", "quantity": 4, "unit": "bag", "purchase_price": 245.0,
                 "mrp": 289.0, "discount": null, "tax_amount": null, "printed_amount": 980.0,
                 "ambiguous": []}],
      "ground_truth_text": "optional exact transcript, for CER/WER",
      "critical_tokens": ["optional extra exact tokens"],
      "notes": ""
    }
  }
}

Rules encoded here: a value printed on the invoice is compared exactly (no unit conversion, no
rounding beyond 0.01); a value the invoice does not print is null in the manifest and any value
extracted for it counts as INVENTED; fields listed in "ambiguous" are excluded from scoring.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SOURCES = {
    "real_photo": "Actual photograph",
    "scan": "Scanned paper invoice",
    "screenshot": "Screenshot / digital render",
    "fixture": "Repository fixture",
    "simulated": "Simulated photograph",
}
ITEM_FIELDS = ("product_name", "quantity", "unit", "purchase_price", "mrp", "discount", "tax_amount",
               "printed_amount")
NUMERIC_FIELDS = ("quantity", "purchase_price", "mrp", "discount", "tax_amount", "printed_amount")
HEADER_FIELDS = ("supplier_name", "invoice_number", "invoice_date")
CONDITIONS = {
    "clear", "low_light", "overexposed", "shadow", "blurry", "small_text", "folded", "crumpled", "faded",
    "rotated_0", "rotated_90", "rotated_180", "rotated_270", "tilted", "straight", "angled",
    "perspective", "curved", "multi_page", "handwritten", "thermal", "dot_matrix",
}


# ---------------------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------------------


def read_manifest(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return {case_id: entry} for both manifest forms."""
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        return dict(raw.get("cases") or {})
    return {k: v for k, v in (raw or {}).items() if not k.startswith("_")}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_case(case_id: str, entry: Dict[str, Any], folder: Optional[Path] = None) -> List[str]:
    """Problems that make a case unusable or untrustworthy as ground truth."""
    errs: List[str] = []
    where = f"{case_id}:"
    prov = entry.get("provenance") or {}
    source = prov.get("source")
    if source not in SOURCES:
        errs.append(f"{where} provenance.source must be one of {sorted(SOURCES)}")
    files = entry.get("files")
    if not isinstance(files, list) or not files:
        errs.append(f"{where} 'files' must list the page images in order")
    elif folder is not None:
        for f in files:
            p = folder / f
            if not p.is_file() or p.stat().st_size == 0:
                errs.append(f"{where} file '{f}' is missing or empty")
    for c in entry.get("conditions") or []:
        if c not in CONDITIONS:
            errs.append(f"{where} unknown condition '{c}' (allowed: {sorted(CONDITIONS)})")
    header = entry.get("header") or {}
    for k, v in header.items():
        if k not in HEADER_FIELDS:
            errs.append(f"{where} unknown header field '{k}'")
        elif v is not None and (not isinstance(v, str) or not v.strip()):
            errs.append(f"{where} header.{k} must be the printed text or null")
    if header.get("invoice_date"):
        from schemas.invoice import parse_invoice_date

        if parse_invoice_date(header["invoice_date"]) is None:
            errs.append(f"{where} header.invoice_date '{header['invoice_date']}' is not a real date")
    items = entry.get("items")
    if not isinstance(items, list) or not items:
        errs.append(f"{where} 'items' must list the invoice line items")
        return errs
    for i, it in enumerate(items, start=1):
        w = f"{where} item {i}:"
        if not isinstance(it.get("product_name"), str) or not it["product_name"].strip():
            errs.append(f"{w} product_name is required")
        for k in NUMERIC_FIELDS:
            v = it.get(k)
            if v is not None and not _is_number(v):
                errs.append(f"{w} {k} must be a number or null (got {v!r})")
        if _is_number(it.get("quantity")) and it["quantity"] <= 0:
            errs.append(f"{w} quantity must be > 0")
        if it.get("unit") is not None and not isinstance(it.get("unit"), str):
            errs.append(f"{w} unit must be the printed text or null")
        for a in it.get("ambiguous") or []:
            if a not in ITEM_FIELDS:
                errs.append(f"{w} ambiguous field '{a}' is not an item field")
        for k in it:
            if k not in ITEM_FIELDS and k != "ambiguous":
                errs.append(f"{w} unknown field '{k}'")
    return errs


def validate_manifest(raw: Dict[str, Any], folder: Optional[Path] = None) -> List[str]:
    cases = read_manifest(raw)
    if not cases:
        return ["manifest has no cases"]
    errs: List[str] = []
    for cid, entry in cases.items():
        errs += validate_case(cid, entry, folder)
    return errs


# ---------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------


def norm_name(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_unit(s: Optional[str]) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _num_eq(a: Any, b: Any, tol: float = 0.011) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < tol


def decimal_corruption(truth: Any, got: Any) -> Optional[str]:
    """Classify a wrong financial value that comes from a lost or misread decimal point."""
    if truth is None or got is None:
        return None
    t, g = float(truth), float(got)
    if abs(t - g) < 0.011 or t == 0:
        return None
    for k in (1, 2, 3):
        if abs(g - t * 10 ** k) < 0.011 * 10 ** k or abs(g * 10 ** k - t) < 0.011:
            return f"decimal shifted by 10^{k}"
    g_txt = str(int(round(g))) if abs(g - round(g)) < 1e-9 else f"{g:g}".replace(".", "")
    for t_txt in {f"{t:.2f}", f"{t:g}"}:
        if "." not in t_txt:
            continue
        if g_txt == t_txt.replace(".", ""):
            return "decimal point dropped"
        if re.fullmatch(re.escape(t_txt).replace(r"\.", r"\d"), g_txt):
            return "decimal point read as a digit"
    return None


def _match_items(extracted: List[Dict[str, Any]], truth: List[Dict[str, Any]]) -> List[Tuple[int, Optional[int]]]:
    """Pair each truth line with at most one extracted line (exact name, then containment, then fuzzy)."""
    used: set = set()
    pairs: List[Tuple[int, Optional[int]]] = []
    names = [norm_name(e.get("product_name")) for e in extracted]
    for ti, t in enumerate(truth):
        tn = norm_name(t["product_name"])
        best, best_score = None, 0.0
        for ei, en in enumerate(names):
            if ei in used or not en:
                continue
            if en == tn:
                score = 3.0
            elif tn in en or en in tn:
                score = 2.0
            else:
                score = difflib.SequenceMatcher(None, tn, en).ratio()
                if score < 0.8:
                    continue
            if score > best_score:
                best, best_score = ei, score
        if best is not None:
            used.add(best)
        pairs.append((ti, best))
    return pairs


def score_items(extracted: List[Dict[str, Any]], truth: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Field-level accuracy, full-line correctness, invented values and decimal corruption.

    A line is FULLY correct only when product name, quantity, rate and amount are all correct
    (a rate or amount the invoice does not print is not required, and is not counted as found).
    """
    fields = ("product_name", "quantity", "unit", "purchase_price", "mrp", "printed_amount")
    out: Dict[str, Any] = {
        "lines": len(truth),
        "lines_found": 0,
        "fully_correct": 0,
        "partially_correct": 0,
        "fields": {f: {"evaluated": 0, "correct": 0, "invented": 0} for f in fields},
        "decimal_corruption": [],
        "extra_lines": 0,
    }
    pairs = _match_items(extracted, truth)
    matched = {e for _, e in pairs if e is not None}
    out["extra_lines"] = len([i for i in range(len(extracted)) if i not in matched])
    for ti, ei in pairs:
        t = truth[ti]
        amb = set(t.get("ambiguous") or [])
        e = extracted[ei] if ei is not None else {}
        if ei is not None:
            out["lines_found"] += 1
        results = {}
        for f in fields:
            if f in amb:
                continue
            tv = t.get(f)
            ev = e.get(f)
            slot = out["fields"][f]
            if tv is None:
                if f != "product_name" and ev not in (None, "") and ei is not None:
                    slot["invented"] += 1  # value extracted for something the invoice does not print
                continue
            slot["evaluated"] += 1
            if f == "product_name":
                ok = ei is not None and norm_name(ev) == norm_name(tv)
            elif f == "unit":
                ok = norm_unit(ev) == norm_unit(tv) and norm_unit(tv) != ""
            else:
                ok = _num_eq(tv, ev)
                if not ok and f in ("purchase_price", "mrp", "printed_amount"):
                    kind = decimal_corruption(tv, ev)
                    if kind:
                        out["decimal_corruption"].append(
                            {"product": t["product_name"], "field": f, "expected": tv, "got": ev, "kind": kind})
            slot["correct"] += int(ok)
            results[f] = ok
        core = ("product_name", "quantity", "purchase_price", "printed_amount")
        core_eval = [results[f] for f in core if f in results]
        required = [f for f in core if f not in amb and (f == "product_name" or t.get(f) is not None)]
        if core_eval and all(core_eval) and len(core_eval) == len(required):
            out["fully_correct"] += 1
        elif any(results.values()):
            out["partially_correct"] += 1
    return out


def score_header(extracted: Dict[str, Any], truth: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Per header field: correct / partial / wrong / missed / invented / correct_empty / not_recorded."""
    if truth is None:
        return {f: "not_recorded" for f in HEADER_FIELDS}
    from schemas.invoice import parse_invoice_date

    out: Dict[str, str] = {}
    for f in HEADER_FIELDS:
        tv = truth.get(f)
        ev = (extracted.get(f) or "").strip() if isinstance(extracted.get(f), str) else extracted.get(f)
        if f not in truth:
            out[f] = "not_recorded"
        elif tv is None:
            out[f] = "invented" if ev else "correct_empty"
        elif not ev:
            out[f] = "missed"
        elif f == "supplier_name":
            a, b = norm_name(tv), norm_name(ev)
            # exact (case/punctuation-insensitive) = correct; the name plus or minus extra words = partial
            out[f] = "correct" if a == b else ("partial" if len(b) >= 6 and (a in b or b in a) else "wrong")
        elif f == "invoice_number":
            out[f] = "correct" if tv.strip().lower() == ev.lower() else "wrong"
        else:
            pt, pe = parse_invoice_date(tv), parse_invoice_date(ev)
            out[f] = "correct" if tv.strip() == ev or (pt is not None and pt == pe) else "wrong"
    return out


def merge_field_counts(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    total: Dict[str, Dict[str, int]] = {}
    for r in rows:
        for f, c in r["fields"].items():
            slot = total.setdefault(f, {"evaluated": 0, "correct": 0, "invented": 0})
            for k in slot:
                slot[k] += c[k]
    return total
