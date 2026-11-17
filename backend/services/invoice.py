"""
Invoice scanning orchestration.

Upload -> file validation -> Header-Guided Dynamic Grocery Extraction pipeline
-> inventory matching -> MRP resolution (services/mrp_lookup.py) -> API response.

Stock is only changed by confirm_and_update_stock(), in one transaction.
"""

import io
import logging
import os
import re
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from services import ocr as ocr_service
from services import mrp_lookup
from services.product_matching import best_name_match, normalize_gtin, normalize_name
from db.models.product import Product
from db.models.purchase import Purchase
from db.models.purchase_item import PurchaseItem
from db.models.supplier import Supplier
from schemas.invoice import (
    CanonicalInvoiceItemSchema,
    DetectedColumnSchema,
    DiagnosticInfo,
    InvoiceConfirmRequest,
    InvoiceConfirmResponse,
    InvoiceExtractResponse,
    MrpLookupSchema,
)
from schemas.product import ProductResponse

logger = logging.getLogger(__name__)

from services.grocery_ocr.engines.ocr_engine import TesseractOCREngine
from services.grocery_ocr.pipeline.invoice_pipeline import InvoicePipeline

USE_NEW_GROCERY_OCR = os.getenv("USE_NEW_GROCERY_OCR", "true").lower() in ("true", "1", "yes")

MAX_PDF_PAGES = 5
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
IMAGE_SIGNATURES = (b"\xff\xd8", b"\x89PNG", b"RIFF", b"BM", b"II*\x00", b"MM\x00*")


class InvoiceConflictError(ValueError):
    """The same supplier invoice was already added to stock."""


class InvoiceValidationError(ValueError):
    """The confirm request is incomplete (e.g. a new product without a selling price)."""


# --------------------------------------------------------------------------
# Backward-compatible helpers (kept for existing callers/tests)
# --------------------------------------------------------------------------

CORE_ROLES = {"qty", "unit", "rate", "purchase_price", "selling_price", "mrp", "discount", "tax", "amount", "line_total"}


class LegacyColumn:
    def __init__(self, col_type: str, x0: float = 0.0, x1: float = 0.0):
        self.type = col_type
        self.x0 = x0
        self.x1 = x1


def detect_columns_from_header_words_py(words: List[Dict[str, Any]], max_w: float = 0.0) -> List[LegacyColumn]:
    HEADER_ROLES = {
        "item": "product", "description": "product", "particulars": "product", "product": "product",
        "qty": "qty", "quantity": "qty",
        "unit": "unit", "uom": "unit",
        "rate": "rate", "price": "rate",
        "amount": "total", "total": "total", "value": "total"
    }
    cols: List[LegacyColumn] = []
    i = 0
    while i < len(words):
        w = words[i]
        txt = str(w.get("text", "")).lower().strip()
        bbox = w.get("bbox", {})
        x0 = float(bbox.get("x0", 0))
        x1 = float(bbox.get("x1", 0))

        if i + 1 < len(words) and words[i + 1].get("text", "").strip() in ("(₹)", "₹", "(rs)", "(inr)", "(Rs.)"):
            x1 = float(words[i + 1].get("bbox", {}).get("x1", x1))
            i += 1

        role = HEADER_ROLES.get(txt)
        if role:
            cols.append(LegacyColumn(role, x0, x1))
        i += 1
    return cols


def is_conflicting_pair_py(type_a: str, type_b: str) -> bool:
    core = CORE_ROLES | {"product"}
    return type_a != type_b and type_a in core and type_b in core


def parse_smart_price_py(tok: Optional[str], allow_zero: bool = False) -> Optional[float]:
    raw = (tok or "").strip()
    if not raw or raw.lower() in {"-", "—", "–", "--", "n/a", "na", "nil", "null", "none", "."}:
        return None
    negative = False
    m = re.match(r"^\((.*)\)$", raw)
    if m:
        negative = True
        raw = m.group(1)
    s = re.sub(r"(?i)₹|rs\.?|inr", " ", raw)
    s = re.sub(r"/-", " ", s)
    s = re.sub(r"/\s*[a-zA-Z]+\b", " ", s)
    s = s.replace("%", " ")
    s = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", s)
    s = s.strip()
    if re.match(r"^\d+,\d{1,2}$", s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    match = re.search(r"[-+]?\d*\.?\d+", s)
    if not match:
        return None
    try:
        val = float(match.group(0))
        if val < 0:
            return val
        if not allow_zero and val == 0:
            return None
        return -val if negative else val
    except ValueError:
        return None


def resolve_item_arithmetic_py(
    qty: Optional[float], rate: Optional[float], total: Optional[float], tax: Optional[float] = None
) -> Dict[str, Any]:
    issues: List[str] = []
    suggestions: List[str] = []
    suggested_rate: Optional[float] = None
    status = "VERIFIED"
    line_total = total
    line_total_source = "INVOICE"

    if qty is not None and rate is not None:
        base = qty * rate
        expected = base + (tax or 0.0)
        if total is None:
            line_total = round(expected, 2)
            line_total_source = "CALCULATED"
            status = "INSUFFICIENT_DATA"
            issues.append("Line amount not printed on invoice; calculated from quantity × rate")
        elif abs(expected - total) > max(1.0, total * 0.01):
            status = "MISMATCH"
            issues.append(f"Amount ₹{total:,.2f} does not match quantity × rate ({qty:,.2f} × ₹{rate:,.2f} = ₹{base:,.2f})")
            if qty > 0 and abs((qty / 10.0) * rate - total) <= max(1.0, total * 0.01):
                clean_q = int(qty / 10.0) if (qty / 10.0).is_integer() else qty / 10.0
                suggestions.append(f"Quantity may be {clean_q} (shifted decimal)")
            elif qty > 0 and abs((qty / 100.0) * rate - total) <= max(1.0, total * 0.01):
                clean_q = int(qty / 100.0) if (qty / 100.0).is_integer() else qty / 100.0
                suggestions.append(f"Quantity may be {clean_q} (shifted decimal)")
    elif qty is not None and rate is None:
        if total is not None and qty > 0:
            suggested_rate = round(total / qty, 2)
            status = "MISMATCH"
            issues.append("Rate could not be read; suggested from line amount ÷ quantity")
    elif total is None and rate is not None:
        issues.append("Quantity not printed on invoice")
        status = "MISMATCH"

    return {
        "quantity": qty,
        "rate": rate,
        "purchase_price": rate,
        "line_total": line_total,
        "line_total_source": line_total_source,
        "status": status,
        "issues": issues,
        "suggestions": suggestions,
        "suggested_rate": suggested_rate,
    }


def suggest_misread_decimal_rate(
    raw_rate: Any, quantity: Optional[float], printed_amount: Optional[float],
    discount: float = 0.0, tax: float = 0.0,
) -> Optional[float]:
    """Rate reading that explains a quantity x rate mismatch by one lost or misread decimal point.

    OCR sometimes reads a decimal point as a digit ("58.75" -> "58575") or drops it. Each
    single-point reading of the rate's digits is tried; a candidate is returned only when it is
    the one reading for which quantity x rate reproduces the printed amount exactly. It is a
    suggestion for the reviewer and is never applied automatically.
    """
    if raw_rate is None or not quantity or quantity <= 0 or printed_amount is None:
        return None
    text = str(raw_rate).strip()
    m = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    if m:
        digits = m.group(1)
    else:
        try:
            value = float(text.replace(",", ""))
        except ValueError:
            return None
        if value != int(value):
            return None
        digits = str(int(value))
    if len(digits) < 3:
        return None
    readings = set()
    for i in range(1, len(digits)):
        readings.add(digits[:i] + "." + digits[i:])  # decimal point dropped
        if i < len(digits) - 1:
            readings.add(digits[:i] + "." + digits[i + 1:])  # decimal point read as a digit
    target = printed_amount + discount - tax
    matches = set()
    for r in readings:
        cand = float(r)
        if cand > 0 and abs(quantity * cand - target) <= 0.011:
            matches.add(round(cand, 2))
    return matches.pop() if len(matches) == 1 else None


def _detect_type(file_bytes: bytes, filename: str) -> str:
    ext = Path((filename or "").lower().strip()).suffix
    if ext == ".pdf" or file_bytes.startswith(b"%PDF"):
        return "pdf"
    if ext in IMAGE_EXTENSIONS or file_bytes.startswith(IMAGE_SIGNATURES):
        return "image"
    if ext in (".txt", ".csv") or ext == "":
        return "text"
    raise ValueError(
        f"Unsupported file format '{ext}'. Supported formats: PDF, Images (PNG, JPG, JPEG, WEBP, BMP, TIFF), and TXT."
    )


# --------------------------------------------------------------------------
# Metadata (never fabricated: missing fields are returned as None)
# --------------------------------------------------------------------------

_TITLE_RE = re.compile(r"^(?:tax\s+invoice|invoice|retail\s+invoice|bill\s+of\s+supply|cash\s+memo|estimate|"
                       r"quotation|original|duplicate|triplicate|delivery\s+challan|purchase\s+bill|bill)\b", re.I)
_PARTY_RE = re.compile(r"\b(?:bill\s*to|ship\s*to|buyer|customer|consignee|sold\s*to|m/s)\b", re.I)
_BUSINESS_RE = re.compile(r"\b(?:traders?|enterprises?|distributors?|agenc(?:y|ies)|wholesalers?|wholesale|stores?|"
                          r"mart|pvt|private|ltd|limited|llp|co\.?|company|suppliers?|marketing|sales|industries|"
                          r"foods?|corporation|brothers|bros|kirana|provisions|general)\b", re.I)
_GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
# "(?:in|n)?voice" also accepts OCR output that clipped the first letters of "Invoice"
_INVNO_RE = re.compile(r"\b(?:(?:in|n)?voice|inv|bill|voucher)\s*(?:no|number|num|#)\.?\s*[:#\-.]?\s*([A-Za-z0-9][A-Za-z0-9/\-_.]{0,30})", re.I)
# A labelled field such as "Invoice No:", "Ph No.", "Order #" is never a business name
_FIELD_LABEL_RE = re.compile(r"\b(?:no|nos|number|num)\s*[.:#]|#\s*\S", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.](?:\d{4}|\d{2})|\d{1,2}[\s\-](?:jan|feb|mar|apr|may|jun|jul|aug|sep|"
                      r"oct|nov|dec)[a-z]*[\s\-,]+\d{2,4})\b", re.I)
_TOTAL_PRIORITY = [
    (re.compile(r"^\s*grand\s*total\b", re.I), 4),
    (re.compile(r"^\s*(?:net\s*(?:amount|payable)|invoice\s*(?:total|value)|amount\s*payable|total\s*payable)\b", re.I), 3),
    (re.compile(r"^\s*total\s*(?:amount|amt)\b", re.I), 2),
    (re.compile(r"^\s*total\b", re.I), 1),
]


def _merge_title_fragments(lines: List[str]) -> List[str]:
    """Rejoin a heading that OCR line reconstruction split into one-word lines.

    Large title text (usually the supplier name) can come back as consecutive single-word
    lines ("SRI", "LAKSHMI", "WHOLESALE", "TRADERS"). Runs of such lines are joined so the
    name can be recognised; all other lines are returned unchanged and in order.
    """
    merged: List[str] = []
    run: List[str] = []
    for line in lines:
        clean = line.strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z&.'\-]+", clean):
            run.append(clean)
            continue
        if len(run) >= 2:
            merged.append(" ".join(run))
        else:
            merged.extend(run)
        run = []
        merged.append(line)
    if len(run) >= 2:
        merged.append(" ".join(run))
    else:
        merged.extend(run)
    return merged


def extract_metadata(lines: List[str], header_text: Optional[str]) -> Dict[str, Any]:
    header_pos = next((i for i, l in enumerate(lines) if header_text and l.strip() == header_text.strip()), len(lines))
    top = lines[: min(header_pos, 15)] if header_pos else lines[:10]

    supplier, supplier_conf = None, 0.0
    fallback = None
    for line in _merge_title_fragments(top):
        clean = line.strip()
        if _PARTY_RE.search(clean):
            break
        if (not clean or _TITLE_RE.match(clean) or _GSTIN_RE.search(clean.upper()) or _INVNO_RE.search(clean)
                or _FIELD_LABEL_RE.search(clean)
                or re.search(r"\b(?:date|dated|phone|ph|mob|mobile|email|gstin|fssai|state)\b", clean, re.I)):
            continue
        words = re.findall(r"[A-Za-z&]{2,}", clean)
        if len(words) < 2 or sum(c.isdigit() for c in clean) > len(clean) * 0.3:
            continue
        if _BUSINESS_RE.search(clean):
            supplier, supplier_conf = clean, 85.0
            break
        fallback = fallback or clean
    if supplier is None and fallback:
        supplier, supplier_conf = fallback, 55.0

    invoice_number, inv_conf = None, 0.0
    invoice_date, date_conf = None, 0.0
    gstin = None
    for line in top or lines[:15]:
        if invoice_number is None:
            m = _INVNO_RE.search(line)
            if m:
                cand = m.group(1).rstrip(".-")
                if cand.lower() not in {"date", "dated", "dt", "no", "number"} and not _DATE_RE.fullmatch(cand):
                    invoice_number, inv_conf = cand, 85.0
        dm = _DATE_RE.search(line)
        if dm and (invoice_date is None or (date_conf < 85 and re.search(r"\bdate", line, re.I))):
            invoice_date = dm.group(1)
            date_conf = 85.0 if re.search(r"\bdate", line, re.I) else 60.0
        gm = _GSTIN_RE.search(line.upper())
        if gm and gstin is None:
            gstin = gm.group(0)

    invoice_total, best_priority = None, 0
    for line in lines[header_pos:] if header_pos < len(lines) else lines:
        for pattern, priority in _TOTAL_PRIORITY:
            if pattern.match(line) and priority >= best_priority:
                nums = re.findall(r"(?:₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?", line, re.I)
                if nums:
                    clean_num = re.sub(r"[^\d.]", "", nums[-1])
                    try:
                        value = float(clean_num)
                    except (ValueError, TypeError):
                        value = None
                    if value is not None and value > 0:
                        invoice_total, best_priority = value, priority
                break

    return {
        "supplier_name": supplier, "supplier_confidence": supplier_conf,
        "invoice_number": invoice_number, "invoice_no_confidence": inv_conf,
        "invoice_date": invoice_date, "date_confidence": date_conf,
        "gstin": gstin, "invoice_total": invoice_total,
    }


# --------------------------------------------------------------------------
# Inventory matching
# --------------------------------------------------------------------------


def match_inventory(name: str, barcode: Optional[str], products: List[Product]) -> Tuple[Optional[Product], float, str]:
    gtin = normalize_gtin(barcode)
    if gtin:
        for p in products:
            if normalize_gtin(p.sku) == gtin:
                return p, 1.0, "GTIN"
    if barcode:
        for p in products:
            if p.sku and p.sku.strip() == barcode.strip():
                return p, 1.0, "SKU"
    m = best_name_match(name, products, lambda p: p.name)
    return m.candidate, m.score, m.method


# --------------------------------------------------------------------------
# Pipeline entry point
# --------------------------------------------------------------------------


def _extract_invoice_with_new_pipeline(
    file_bytes: bytes, filename: str, db: Session, shop_id: UUID
) -> InvoiceExtractResponse:
    shop_products = db.query(Product).filter(Product.shop_id == shop_id).all()
    pipeline = InvoicePipeline(ocr_engine=TesseractOCREngine())
    extracted = pipeline.process(file_bytes, filename, candidate_products=shop_products)

    if extracted.status == "FAILED":
        raise ValueError(extracted.reason or "Failed to process invoice document.")

    # External MRP lookup integration
    queries = []
    for it in extracted.items:
        p_name = it.normalized_product_name or it.raw_product_name
        gtin = normalize_gtin(it.barcode)
        queries.append(mrp_lookup.LookupQuery(product_name=p_name, gtin=gtin, sku=None))
    provider = mrp_lookup.get_provider()
    lookups = mrp_lookup.lookup_mrp_batch(queries, provider) if queries else []

    items: List[CanonicalInvoiceItemSchema] = []
    for idx, it in enumerate(extracted.items):
        q = float(it.quantity) if it.quantity is not None else None
        pp = float(it.purchase_price) if it.purchase_price is not None else None
        sp = float(it.selling_price) if it.selling_price is not None else None
        m = float(it.mrp) if it.mrp is not None else None
        prn = float(it.printed_amount) if it.printed_amount is not None else None
        calc = float(it.calculated_amount) if it.calculated_amount is not None else None
        tot = prn if prn is not None else calc
        disc = float(it.discount) if it.discount is not None else 0.0
        tax = float(it.tax_amount) if it.tax_amount is not None else 0.0

        if tot is None and it.raw_row_text:
            num_matches = re.findall(r"\b\d[\d,]*(?:\.\d{2})\b", it.raw_row_text)
            if num_matches:
                cand_tot = parse_smart_price_py(num_matches[-1])
                if cand_tot is not None and cand_tot > 0:
                    tot = cand_tot
                    prn = cand_tot

        if q is None and pp is not None and pp > 0 and tot is not None:
            pre_tax = tot + disc - tax
            cand_q = round(pre_tax / pp, 3)
            for test_q in (round(cand_q), round(cand_q, 1), cand_q):
                if test_q > 0 and abs(test_q * pp - pre_tax) <= max(1.5, tot * 0.01):
                    q = float(test_q)
                    break

        if pp is None and q is not None and q > 0 and tot is not None:
            pre_tax = tot + disc - tax
            pp = round(pre_tax / q, 2)

        if tot is None and q is not None and pp is not None:
            tot = round(q * pp - disc + tax, 2)

        verified = (it.validation_status == "VERIFIED") or (q is not None and pp is not None and tot is not None and abs(q * pp - disc + tax - tot) <= 1.5)
        needs_review = (
            it.review_status in ("REVIEW_REQUIRED", "UNKNOWN_REVIEW", "NON_GROCERY")
            or not verified
            or pp is None
            or q is None
            or (it.ocr_confidence is not None and it.ocr_confidence < 85.0)
        )

        norm_unit = it.unit.lower().strip() if it.unit else None
        orig = {
            "name": it.raw_product_name,
            "quantity": q,
            "unit": norm_unit,
            "purchase_price": pp,
            "selling_price": sp,
            "mrp": m,
            "discount": float(it.discount) if it.discount is not None else None,
            "gst_rate": float(it.gst_rate) if it.gst_rate is not None else None,
            "line_total": tot,
            "brand": it.brand,
            "category": it.category,
            "pack_size": it.package_size.raw_text if it.package_size else None,
        }

        matched_prod = None
        matched_prod_id = None
        matched_prod_name = None
        match_score = None
        matched_id_val = it.metadata.get("matched_product_id") or it.matched_product_id
        if matched_id_val:
            matched_prod = next((p for p in shop_products if str(p.id) == str(matched_id_val)), None)
            if matched_prod:
                matched_prod_id = matched_prod.id
                matched_prod_name = matched_prod.name
                match_score = float(it.metadata.get("match_score", 1.0))
        if matched_prod is None and shop_products:
            p_name = it.normalized_product_name or it.raw_product_name
            cand, score, _ = match_inventory(p_name, it.barcode, shop_products)
            if cand and score >= 0.7:
                matched_prod = cand
                matched_prod_id = cand.id
                matched_prod_name = cand.name
                match_score = score

        lookup = lookups[idx] if idx < len(lookups) else None
        store_mrp = matched_prod.mrp if matched_prod is not None else None
        mrp_val, mrp_src, mrp_issues, mrp_needs_review = mrp_lookup.resolve_line_mrp(m, lookup, store_mrp)
        if mrp_needs_review:
            needs_review = True
        arith = resolve_item_arithmetic_py(q, pp, tot, tax)
        arith_status = arith["status"] if arith["status"] != "VERIFIED" else it.validation_status
        if arith_status == "MISMATCH":
            needs_review = True
        line_validation_issues = list(it.validation_issues or []) + list(mrp_issues or []) + list(arith.get("issues", []))
        line_suggestions = list(arith.get("suggestions") or [])
        line_suggested_rate = arith.get("suggested_rate")
        if arith_status == "MISMATCH" and pp is not None and prn is not None:
            raw_rate = (it.raw_cells or {}).get("rate") or (it.raw_cells or {}).get("purchase_price") or pp
            misread = suggest_misread_decimal_rate(raw_rate, q, prn, disc, tax)
            if misread is not None and abs(misread - pp) > 0.005:
                line_suggestions.append(
                    f"Rate ₹{pp:,.2f} may be a misread decimal point: ₹{misread:,.2f} × {q:g} = ₹{prn:,.2f} "
                    "(printed amount). Please check the invoice and confirm."
                )
                line_suggested_rate = line_suggested_rate if line_suggested_rate is not None else misread
                needs_review = True
        line_total_source = "INVOICE" if prn is not None else arith.get("line_total_source", "UNKNOWN")
        mrp_lookup_schema = MrpLookupSchema(**lookup.to_dict()) if lookup else MrpLookupSchema(
            status="FOUND" if mrp_val else "NOT_FOUND",
            provider="invoice",
            message="Read from invoice" if mrp_val else "Not printed",
            mrp=mrp_val,
            match_method="invoice" if mrp_val else "none",
        )

        items.append(
            CanonicalInvoiceItemSchema(
                id=it.item_id,
                product_name=it.normalized_product_name or it.raw_product_name,
                quantity=q,
                unit=norm_unit,
                rate=pp,
                purchase_price=pp,
                selling_price=sp,
                mrp=mrp_val,
                mrp_source=mrp_src,
                invoice_mrp=m,
                store_mrp=store_mrp,
                mrp_lookup=mrp_lookup_schema,
                raw_rate=pp,
                raw_purchase_price=pp,
                raw_selling_price=sp,
                raw_mrp=m,
                discount=float(it.discount) if it.discount is not None else None,
                discount_pct=float(it.discount_pct) if it.discount_pct is not None else None,
                taxable_amount=float(it.taxable_amount) if it.taxable_amount is not None else None,
                tax_amount=float(it.tax_amount) if it.tax_amount is not None else None,
                gst_rate=float(it.gst_rate) if it.gst_rate is not None else None,
                hsn_code=it.hsn_code,
                barcode=it.barcode,
                line_total=tot,
                amount=tot,
                printed_amount=prn,
                calculated_amount=calc,
                line_total_source=line_total_source,
                arithmetic_status=arith_status,
                purchasePrice=pp,
                confidence=float(it.ocr_confidence or 95.0),
                confidence_level="HIGH" if not needs_review else "LOW",
                needs_review=needs_review,
                source_text=it.raw_row_text,
                raw_cells=it.raw_cells,
                extraction_method="TABLE_STRUCTURED",
                validation_issues=line_validation_issues,
                suggestions=line_suggestions,
                suggested_rate=line_suggested_rate,
                matched_product_id=matched_prod_id,
                matched_product_name=matched_prod_name,
                match_score=match_score,
                pack_size=(
                    float(it.package_size.value)
                    if (it.package_size and it.package_size.value is not None)
                    else None
                ),
                pack_size_unit=it.package_size.unit if it.package_size else None,
                classification_status=(
                    "GROCERY_CONFIDENT"
                    if it.is_grocery and it.review_status == "CONFIRMED"
                    else ("NON_GROCERY" if not it.is_grocery else "GROCERY_REVIEW")
                ),
                is_grocery=it.is_grocery,
                brand=it.brand,
                normalized_name=it.normalized_product_name or it.raw_product_name,
                category=it.category,
                is_verified=verified,
                user_edited=False,
                original_values=orig,
            )
        )

    tot_amt = round(sum(i.line_total for i in items if i.line_total is not None), 2)
    tot_units = round(sum(i.quantity for i in items if i.quantity is not None), 2)
    hdr_detected = len(extracted.metadata.tables_detected) > 0 and extracted.metadata.tables_detected[0].has_table
    t0 = extracted.metadata.tables_detected[0] if hdr_detected else None

    columns = (
        [
            DetectedColumnSchema(role=c.role, header_text=c.header_text, x_start=c.x_start, x_end=c.x_end)
            for c in (t0.columns or [])
        ]
        if t0
        else []
    )

    raw_text = extracted.metadata.ocr_evidence.full_text if extracted.metadata.ocr_evidence else ""
    text_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    hdr_text = t0.header_text if t0 else None
    meta = extract_metadata(text_lines, hdr_text)

    supplier_name = extracted.supplier_name or meta.get("supplier_name")
    supplier_conf = 85.0 if extracted.supplier_name else float(meta.get("supplier_confidence", 0.0))
    invoice_number = extracted.invoice_number or meta.get("invoice_number")
    inv_conf = 85.0 if extracted.invoice_number else float(meta.get("invoice_no_confidence", 0.0))
    invoice_date = extracted.invoice_date or meta.get("invoice_date")
    date_conf = 85.0 if extracted.invoice_date else float(meta.get("date_confidence", 0.0))
    gstin = meta.get("gstin")
    meta_total = meta.get("invoice_total")
    tot_amt_res = tot_amt if tot_amt > 0 else (meta_total or 0.0)

    is_pdf = filename.lower().endswith(".pdf") or file_bytes.startswith(b"%PDF")
    is_txt = filename.lower().endswith(".txt") or filename.lower().endswith(".csv")
    if is_pdf:
        is_digital = any(
            p.metadata.get("is_digital") or "stream" in str(p.metadata.get("source", ""))
            for p in (extracted.metadata.ocr_evidence.pages if extracted.metadata.ocr_evidence else [])
        )
        if is_digital:
            engine_used = "backend_pdf_direct"
        else:
            engine_used = "backend_pdf_ocr_scanned"
    elif is_txt:
        engine_used = "backend_text_direct"
    else:
        engine_used = "backend_ocr_pipeline"

    diag = DiagnosticInfo(
        document_type=extracted.metadata.document_type,
        engine_used=engine_used,
        total_raw_lines=(
            sum(len(p.lines) for p in extracted.metadata.ocr_evidence.pages)
            if extracted.metadata.ocr_evidence
            else len(items)
        ),
        total_raw_words=len(raw_text.split()),
        header_detected=hdr_detected,
        header_text=t0.header_text if t0 else None,
        detected_columns=[c.role for c in (t0.columns or [])] if t0 else [],
        columns=columns,
        rows=[],
        detected_sections=["HEADER", "LINE_ITEMS"] if hdr_detected else [],
        warnings=extracted.metadata.warnings,
        ocr_psm="3",
        ocr_language_data="eng+osd",
        pages_processed=extracted.metadata.page_count,
        mrp_provider="openmrp",
    )

    excel_download_url = (
        f"/api/v1/invoices/{extracted.invoice_id}/excel"
        if extracted.metadata.custom_properties.get("xlsx_file_path")
        else None
    )

    if items:
        valid_items = [i for i in items if i.confidence >= 60 and i.purchase_price is not None and i.quantity is not None]
        if valid_items and (len(valid_items) / len(items)) >= 0.7:
            status_str = "success"
            reason_str = "High confidence table reconstruction"
        else:
            status_str = "needs_review"
            reason_str = "Low confidence or missing critical fields in reconstructed table"
    else:
        status_str = "needs_review"
        reason_str = (
            extracted.metadata.warnings[0]
            if extracted.metadata.warnings
            else "No product line items were detected in the document"
        )

    return InvoiceExtractResponse(
        id=extracted.invoice_id,
        supplier_name=supplier_name,
        supplier_confidence=supplier_conf,
        invoice_number=invoice_number,
        invoice_no_confidence=inv_conf,
        invoice_date=invoice_date,
        date_confidence=date_conf,
        gstin=gstin,
        invoice_total=tot_amt_res,
        total_amount=tot_amt_res,
        total_units=tot_units,
        total_items=len(items),
        confidence_score=round(sum(i.confidence for i in items) / len(items), 1) if items else 90.0,
        raw_ocr_text=raw_text,
        engine_used=engine_used,
        extraction_method="TABLE_STRUCTURED" if hdr_detected else "TEXT_LINE_ITEM",
        items=items,
        status=status_str,
        reason=reason_str,
        diagnostics=diag,
        excel_download_url=excel_download_url,
        total_grocery_items=sum(1 for i in items if i.is_grocery and i.classification_status == "GROCERY_CONFIDENT"),
        total_review_items=sum(1 for i in items if i.classification_status in ("GROCERY_REVIEW", "UNKNOWN_REVIEW")),
        total_excluded_items=sum(1 for i in items if i.classification_status == "NON_GROCERY"),
        pipeline_stages=extracted.metadata.pipeline_stages_completed,
    )


def extract_invoice_from_bytes(
    file_bytes: bytes, filename: str, db: Session, shop_id: UUID
) -> InvoiceExtractResponse:
    """
    Primary invoice scanning orchestrator.
    Routes directly to the Header-Guided Dynamic Grocery Extraction pipeline.
    """
    if not file_bytes or len(file_bytes.strip()) == 0:
        raise ValueError("Uploaded file is empty. Please upload a valid invoice document.")

    return _extract_invoice_with_new_pipeline(file_bytes, filename, db, shop_id)



# --------------------------------------------------------------------------
# Confirmation: one transaction for products, stock and the purchase record
# --------------------------------------------------------------------------


def _merge_duplicate_lines(items):
    """Same product twice on one invoice -> one stock movement."""
    merged: List[Any] = []
    for item in items:
        key_id = item.matched_product_id
        key_name = normalize_name(item.name)
        existing = next((m for m in merged if (key_id and m.matched_product_id == key_id)
                         or (normalize_name(m.name) == key_name)), None)
        if existing is None:
            merged.append(item.model_copy())
            continue
        if abs(existing.purchase_price - item.purchase_price) > 0.005:
            raise InvoiceValidationError(
                f"'{item.name}' appears twice with different purchase prices "
                f"(₹{existing.purchase_price:g} and ₹{item.purchase_price:g}); correct or remove one line."
            )
        old_qty = existing.quantity
        existing.quantity = old_qty + item.quantity
        if existing.line_amount is not None or item.line_amount is not None:
            existing.line_amount = (
                (existing.line_amount if existing.line_amount is not None else round(old_qty * existing.purchase_price, 2))
                + (item.line_amount if item.line_amount is not None else round(item.quantity * item.purchase_price, 2))
            )
        for attr in ("selling_price", "mrp", "mrp_source"):
            if getattr(existing, attr) is None and getattr(item, attr) is not None:
                setattr(existing, attr, getattr(item, attr))
    return merged


def confirm_and_update_stock(db: Session, shop_id: UUID, confirm_in: InvoiceConfirmRequest) -> InvoiceConfirmResponse:
    try:
        items = _merge_duplicate_lines(confirm_in.items)

        supplier_id = confirm_in.supplier_id
        if supplier_id:
            supplier = db.query(Supplier).filter(Supplier.id == supplier_id, Supplier.shop_id == shop_id).first()
            if not supplier:
                raise InvoiceValidationError("Supplier not found for this shop.")
        elif confirm_in.supplier_name and confirm_in.supplier_name.strip():
            supplier = db.query(Supplier).filter(
                Supplier.shop_id == shop_id,
                Supplier.supplier_name.ilike(confirm_in.supplier_name.strip()),
            ).first()
            if not supplier:
                supplier = Supplier(shop_id=shop_id, supplier_name=confirm_in.supplier_name.strip())
                db.add(supplier)
                db.flush()
            supplier_id = supplier.id

        invoice_number = (confirm_in.invoice_number or "").strip() or None
        if invoice_number:
            dup = db.query(Purchase).filter(
                Purchase.shop_id == shop_id,
                Purchase.invoice_number == invoice_number,
                Purchase.supplier_id == supplier_id,
            ).first()
            if dup:
                when = dup.created_at.strftime("%d/%m/%Y") if dup.created_at else "earlier"
                raise InvoiceConflictError(
                    f"Invoice {invoice_number} from this supplier was already added to stock ({when}). "
                    "Stock was not changed again."
                )

        # Resolve every product before changing anything
        resolved: List[Tuple[Any, Optional[Product]]] = []
        for item in items:
            product = None
            if item.matched_product_id:
                product = db.query(Product).filter(Product.id == item.matched_product_id, Product.shop_id == shop_id).first()
                if product is None:
                    raise InvoiceValidationError(f"Matched product for '{item.name}' does not belong to this shop.")
            if product is None:
                product = db.query(Product).filter(Product.shop_id == shop_id, Product.name.ilike(item.name.strip())).first()
            resolved.append((item, product))

        missing_sp = [item.name for item, product in resolved if product is None and item.selling_price is None]
        if missing_sp:
            raise InvoiceValidationError("Selling price is required for new products: " + ", ".join(missing_sp))

        db_purchase = Purchase(shop_id=shop_id, supplier_id=supplier_id, total_amount=0.0,
                               invoice_number=invoice_number, invoice_date=confirm_in.invoice_date,
                               processing_status="CONFIRMED", review_status="REVIEWED")
        db.add(db_purchase)
        db.flush()

        now = datetime.now(timezone.utc)
        total_amount = 0.0
        total_units = 0.0
        restocked = created = 0
        saved_products: List[Product] = []
        for item, product in resolved:
            qty = int(item.quantity)
            mrp_source = (item.mrp_source or "MANUAL") if item.mrp is not None else None
            if product is not None:
                product.is_active = True
                product.current_stock = (product.current_stock or 0) + qty
                product.purchase_price = item.purchase_price
                if item.selling_price is not None:
                    product.selling_price = item.selling_price
                restocked += 1
            else:
                product = Product(
                    shop_id=shop_id,
                    name=item.name.strip(),
                    category=item.category or "Groceries",
                    purchase_price=item.purchase_price,
                    selling_price=item.selling_price,
                    current_stock=qty,
                    unit=item.unit or "pcs",
                    reorder_level=10,
                    is_active=True,
                )
                db.add(product)
                created += 1
            # A missing MRP never clears a stored one
            if item.mrp is not None:
                product.mrp = item.mrp
                product.mrp_source = mrp_source
                product.mrp_updated_at = now
            db.add(product)
            db.flush()
            saved_products.append(product)

            line_amount = item.line_amount if item.line_amount is not None else round(qty * item.purchase_price, 2)
            total_amount += line_amount
            total_units += qty
            db.add(PurchaseItem(
                purchase_id=db_purchase.id,
                product_id=product.id,
                quantity=qty,
                purchase_price=item.purchase_price,
                line_amount=line_amount,
                mrp=item.mrp,
                mrp_source=mrp_source,
            ))

        db_purchase.total_amount = round(total_amount, 2)
        db.commit()
        db.refresh(db_purchase)

        # Trigger System Notification for successful invoice stock update
        try:
            from db.models.shop import Shop
            from services.notification import create_notification
            from schemas.notification import NotificationCreate

            shop = db.query(Shop).filter(Shop.id == shop_id).first()
            if shop and shop.owner_id:
                inv_display = f" #{invoice_number}" if invoice_number else ""
                create_notification(
                    db,
                    NotificationCreate(
                        user_id=shop.owner_id,
                        shop_id=shop_id,
                        title=f"Invoice Processed{inv_display}",
                        message=f"Successfully added {total_units} units across {len(items)} items to inventory. Total batch: ₹{db_purchase.total_amount:,.2f}.",
                        category="system",
                        priority="medium",
                        deep_link="/inventory",
                        event_key=f"invoice_confirmed:{db_purchase.id}"
                    ),
                    cooldown_hours=24
                )
        except Exception:
            pass

        return InvoiceConfirmResponse(
            purchase_id=db_purchase.id,
            shop_id=shop_id,
            supplier_name=confirm_in.supplier_name,
            invoice_number=invoice_number,
            total_amount=db_purchase.total_amount,
            total_units=total_units,
            items_restocked=restocked,
            items_created=created,
            created_at=db_purchase.created_at or now,
            processing_status=db_purchase.processing_status or "CONFIRMED",
            review_status=db_purchase.review_status or "REVIEWED",
            saved_products=[ProductResponse.model_validate(p) for p in saved_products],
        )
    except Exception:
        db.rollback()
        raise
