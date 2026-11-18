"""
Phase 3A follow-up (approved): grand-total reconciliation (C2), column boundaries for left-aligned
headings, three-decimal precision end to end, and paid + free quantities.

Inputs are generic test data (not taken from any supplied invoice).
"""

import uuid
from decimal import Decimal
from typing import List, Optional

import pytest

from services import mrp_lookup
from services.grocery_ocr.schemas.invoice import ExtractedInvoice, InvoiceProcessingMetadata
from services.grocery_ocr.schemas.invoice_item import ExtractedInvoiceItem
from services.grocery_ocr.schemas.ocr import OCRDocumentResult
from services.invoice_reconciliation import find_printed_totals, reconcile_invoice_total

D = Decimal


class _NoProducts:
    def query(self, *a, **k):
        return self

    def filter(self, *a, **k):
        return self

    def all(self):
        return []


def item(name, qty=None, rate=None, amount=None, **kw) -> ExtractedInvoiceItem:
    d = lambda v: Decimal(str(v)) if v is not None else None  # noqa: E731
    return ExtractedInvoiceItem(item_id=f"i_{uuid.uuid4().hex[:6]}", raw_product_name=name,
                                normalized_product_name=name, quantity=d(qty), purchase_price=d(rate),
                                printed_amount=d(amount), validation_status="VERIFIED", ocr_confidence=95.0, **kw)


def run_api(monkeypatch, items: List[ExtractedInvoiceItem], text: str = "", custom: Optional[dict] = None):
    from services import invoice as inv

    meta = InvoiceProcessingMetadata(filename="t.png")
    meta.custom_properties.update(custom or {})
    meta.ocr_evidence = OCRDocumentResult(filename="t.png", full_text=text)
    result = ExtractedInvoice(invoice_id="inv_t", original_filename="t.png", status="SUCCESS", items=items,
                              total_items_count=len(items), metadata=meta)
    monkeypatch.setattr(inv.InvoicePipeline, "process", lambda self, *a, **k: result)
    monkeypatch.setattr(mrp_lookup, "get_provider", lambda: mrp_lookup.NoProvider())
    return inv._extract_invoice_with_new_pipeline(b"x", "t.png", _NoProducts(), uuid.uuid4())


# ------------------------------------------------------------------------------------- C2


def test_c2_printed_total_found_and_tax_subtotal_not_mistaken_for_it():
    p = find_printed_totals(["Total Quantity 110.0", "Total Tax (₹) 215.76", "Grand Total (₹) 46,885.80"])
    assert p.reliable and p.total == D("46885.80") and p.adjustments["tax"] == D("215.76")


def test_c2_label_and_value_on_separate_lines():
    p = find_printed_totals(["NETAMOUNT :", "588.00"])
    assert p.reliable and p.total == D("588.00")


def test_c2_conflicting_totals_mean_reconciliation_not_completed():
    r = reconcile_invoice_total(["Grand Total 1,210.00", "Net Payable 1,310.00"], [D("1210.00")])
    assert r["status"] == "not_completed" and "not certain" in r["message"]


def test_c2_no_printed_total_reported_as_not_completed():
    r = reconcile_invoice_total(["Item Qty Rate Amount", "Salt 20 22.00 440.00"], [D("440.00")])
    assert r["status"] == "not_completed" and "could not be completed" in r["message"]


@pytest.mark.parametrize("lines,amounts,used", [
    (["Grand Total 1,210.00"], ["200.00", "660.00", "350.00"], []),
    (["Round Off -0.40", "Grand Total 99.60"], ["100.00"], []),  # within the rounding tolerance
    (["GSTVALUE", "Total Tax 28.00", "NETAMOUNT : 588.00"], ["560.00"], ["tax"]),
    (["Freight 50.00", "Cash Discount 10.00", "Net Payable 540.00"], ["500.00"], ["charges", "discount"]),
    (["Net Amount 539.996"], ["90.000", "449.996"], []),
])
def test_c2_matches_with_printed_adjustments(lines, amounts, used):
    r = reconcile_invoice_total(lines, [D(a) for a in amounts])
    assert r["status"] == "matched", r
    assert sorted(r["adjustments_used"]) == sorted(used)


def test_c2_silent_decimal_loss_in_quantity_and_amount_is_caught():
    """Reproduces the remaining silent error: qty 2.50 -> 250 and amount 350.00 -> 35000 keep
    qty x rate = amount, so only the printed total reveals it."""
    r = reconcile_invoice_total(["Grand Total: 1,210.00"], [D("200.00"), D("660.00"), D("35000.00")])
    assert r["status"] == "mismatch"
    assert list(r["line_suggestions"]) == [2] and "₹350.00" in r["line_suggestions"][2]


def test_c2_api_warns_never_changes_values_and_never_rejects(monkeypatch):
    items = [item("BASMATI 1KG", 1.25, 160, 200), item("CASHEW W320", 0.75, 880, 660),
             item("MOONG DAL", 250, 140, 35000)]  # read with lost decimals, arithmetic agrees
    res = run_api(monkeypatch, items, "Item Qty Rate Amount\nGrand Total: 1,210.00")
    moong = res.items[2]
    assert moong.quantity == 250.0 and moong.line_total == 35000.0  # unchanged
    assert moong.needs_review is True and any("₹350.00" in s for s in moong.suggestions)
    assert res.items[0].needs_review is False  # unaffected lines stay as they were
    assert res.status == "needs_review" and res.total_reconciliation["status"] == "mismatch"
    assert res.printed_total == 1210.0 and len(res.items) == 3


def test_c2_api_matched_and_not_completed(monkeypatch):
    ok = run_api(monkeypatch, [item("SALT", 20, 22, 440)], "Grand Total 440.00")
    assert ok.total_reconciliation["status"] == "matched" and ok.status == "success"
    nc = run_api(monkeypatch, [item("SALT", 20, 22, 440)], "no total printed here")
    assert nc.total_reconciliation["status"] == "not_completed" and nc.printed_total is None
    assert nc.items[0].line_total == 440.0


# ------------------------------------------------------------------------------------- column boundaries


def _w(text, x0, x1, y=100.0):
    from services.grocery_ocr.schemas.ocr import BoundingBox, OCRWord

    return OCRWord(text=text, bbox=BoundingBox(x0=x0, y0=y, x1=x1, y1=y + 20), confidence=95.0, page_number=1)


def test_boundary_moves_out_of_right_aligned_value_block():
    from services.grocery_ocr.extraction.dynamic_schema_generator import DynamicSchemaGenerator as G

    values = [_w("0", 1055, 1069), _w("1", 1057, 1069, 140), _w("0", 1055, 1069, 180)]
    assert G._split_outside_value_block(1060.0, values, next_hx0=1090.0) == pytest.approx(1079.5)


def test_boundary_not_moved_when_block_runs_into_the_next_heading():
    from services.grocery_ocr.extraction.dynamic_schema_generator import DynamicSchemaGenerator as G

    values = [_w("12345", 1040, 1100)]  # extends past the next heading start: ambiguous, left alone
    assert G._split_outside_value_block(1060.0, values, next_hx0=1090.0) == 1060.0


def test_boundary_not_moved_by_product_name_text():
    """Regression (blurry capture, unreadable headings): a run of product-name words is not a stack of
    values, so it must never pull a boundary across the table and drop the next row's values."""
    from services.grocery_ocr.extraction.dynamic_schema_generator import DynamicSchemaGenerator as G

    words = [_w("ORGANIC", 600, 700), _w("CHANA", 690, 760, 140), _w("DAL", 755, 800, 180)]
    assert G._split_outside_value_block(679.0, words, next_hx0=819.0) == 679.0


def test_boundary_untouched_when_it_lies_in_a_gap():
    from services.grocery_ocr.extraction.dynamic_schema_generator import DynamicSchemaGenerator as G

    values = [_w("0", 1000, 1015), _w("24", 1100, 1130)]
    assert G._split_outside_value_block(1060.0, values, next_hx0=1090.0) == 1060.0


def test_value_across_a_column_boundary_is_flagged_for_review():
    from services.grocery_ocr.extraction.column_wise_extractor import ColumnWiseExtractor
    from services.grocery_ocr.extraction.table_reconstructor import BaseTableReconstructor
    from services.grocery_ocr.schemas.table import DetectedColumn

    cols = [DetectedColumn(role="product", header_text="Item", column_index=0, x_start=0.0, x_end=300.0),
            DetectedColumn(role="cases", header_text="Cs", column_index=1, x_start=300.0, x_end=360.0),
            DetectedColumn(role="qty", header_text="Pcs", column_index=2, x_start=360.0, x_end=460.0),
            DetectedColumn(role="rate", header_text="Rate", column_index=3, x_start=460.0, x_end=600.0),
            DetectedColumn(role="total", header_text="Amount", column_index=4, x_start=600.0, x_end=None)]
    words = [_w("SALT", 10, 60), _w("1KG", 65, 95), _w("12", 340, 370), _w("22.00", 500, 560), _w("264.00", 640, 700)]
    cells, _warn, review = BaseTableReconstructor()._associate_row_words_to_columns(1, words, cols)
    assert review is True and cells[1].review_required and "boundary" in cells[1].review_reason
    from services.grocery_ocr.schemas.table import TableRow

    rec = ColumnWiseExtractor().extract_row(TableRow(row_index=1, cells=cells, raw_text="SALT 1KG 12 22.00 264.00"), cols)
    assert any("boundary" in r for r in rec.review_reasons)


def test_value_inside_its_column_is_not_flagged():
    from services.grocery_ocr.extraction.table_reconstructor import BaseTableReconstructor
    from services.grocery_ocr.schemas.table import DetectedColumn

    cols = [DetectedColumn(role="product", header_text="Item", column_index=0, x_start=0.0, x_end=300.0),
            DetectedColumn(role="qty", header_text="Qty", column_index=1, x_start=300.0, x_end=None)]
    cells, _w2, review = BaseTableReconstructor()._associate_row_words_to_columns(1, [_w("SALT", 10, 60), _w("12", 320, 345)], cols)
    assert review is False and not cells[1].review_required


# ------------------------------------------------------------------------------------- precision + promotions (extraction)


def test_excel_export_shows_a_printed_third_decimal():
    import io

    import openpyxl

    from services.grocery_ocr.excel.workbook_generator import BaseWorkbookGenerator

    inv = ExtractedInvoice(invoice_id="x", original_filename="x.png", status="SUCCESS",
                           items=[item("FRUIT NUT 10RS", 12, D("7.143"), D("85.716"))],
                           metadata=InvoiceProcessingMetadata(filename="x.png"))
    ws = openpyxl.load_workbook(io.BytesIO(BaseWorkbookGenerator().generate(inv)))["Grocery Items"]
    rate = ws.cell(row=2, column=10)
    assert rate.value == 7.143 and rate.number_format == "#,##0.00#"


def test_extraction_paid_plus_free_shows_received_units(monkeypatch):
    it = item("SOAP 75G", 10, D("35.00"), D("350.00"))
    it.metadata.update({"quantity_details": {"raw_quantity": "10+1", "paid_plus_free": True, "paid_quantity": "10",
                                             "free_quantity": "1"},
                        "review_reasons": ["Promotion printed as '10+1': 10 paid + 1 free = 11 units received."]})
    out = run_api(monkeypatch, [it]).items[0]
    assert (out.quantity, out.paid_quantity, out.free_quantity) == (11.0, 10.0, 1.0)
    assert out.purchase_price == 35.0 and out.line_total == 350.0  # printed values; nothing redistributed
    assert out.arithmetic_status != "MISMATCH"  # arithmetic uses the paid units
    assert out.needs_review is True  # user confirms before stock is posted


def test_extraction_free_line_is_all_free_units(monkeypatch):
    it = item("REFILL 180ML", 6, D("0.00"), D("0.00"))
    it.metadata.update({"is_free_item": True})
    out = run_api(monkeypatch, [it]).items[0]
    assert (out.quantity, out.paid_quantity, out.free_quantity, out.purchase_price) == (6.0, 0.0, 6.0, 0.0)
    assert out.needs_review is True


def test_extraction_totals_keep_three_decimals(monkeypatch):
    res = run_api(monkeypatch, [item("COOKIE A", 12, D("5.249"), D("62.988")), item("COOKIE B", 12, D("7.143"), D("85.716"))],
                  "Net Amount : 148.704")
    assert res.total_amount == 148.704 and res.total_reconciliation["status"] == "matched"
