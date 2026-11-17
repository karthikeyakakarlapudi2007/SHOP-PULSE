"""
Unit tests for the real-photo validation harness (tests/validation_scoring.py): manifest
validation and scoring rules. Fast; no OCR. The inputs here are hand-written test data for the
harness itself, not validation evidence.
"""

import json
from pathlib import Path

import pytest

from validation_scoring import (
    decimal_corruption,
    read_manifest,
    score_header,
    score_items,
    validate_manifest,
)

TEMPLATE = Path(__file__).resolve().parents[2] / "validation" / "real_invoices" / "manifest.template.json"


def case(**over):
    base = {
        "provenance": {"source": "real_photo"},
        "files": ["a.jpg"],
        "header": {"supplier_name": "Balaji Traders", "invoice_number": "BT-1", "invoice_date": "08/10/2026"},
        "items": [{"product_name": "Tata Salt 1kg", "quantity": 20, "unit": "pkt", "purchase_price": 22.0,
                   "mrp": None, "printed_amount": 440.0}],
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- manifest validation

def test_template_parses_and_flags_its_placeholders():
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert list(read_manifest(raw)) == ["inv01"]
    problems = validate_manifest(raw)  # without a folder: no file checks
    assert any("not a real date" in p for p in problems)  # placeholder date must be replaced


def test_valid_manifest_and_old_format(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    assert validate_manifest({"schema_version": 2, "cases": {"c1": case()}}, tmp_path) == []
    assert validate_manifest({"c1": case()}, tmp_path) == []  # schema 1 still read


@pytest.mark.parametrize("bad,needle", [
    ({"provenance": {"source": "unknown"}}, "provenance.source"),
    ({"files": []}, "'files'"),
    ({"conditions": ["sunny"]}, "unknown condition"),
    ({"header": {"invoice_date": "31/02/2026"}}, "not a real date"),
    ({"items": [{"product_name": "X", "quantity": "4"}]}, "must be a number or null"),
    ({"items": [{"product_name": "X", "quantity": 0}]}, "quantity must be > 0"),
    ({"items": [{"product_name": "", "quantity": 1}]}, "product_name is required"),
    ({"items": [{"product_name": "X", "qty": 1}]}, "unknown field 'qty'"),
    ({"items": [{"product_name": "X", "ambiguous": ["colour"]}]}, "not an item field"),
])
def test_manifest_problems_are_reported(tmp_path, bad, needle):
    (tmp_path / "a.jpg").write_bytes(b"x")
    problems = validate_manifest({"c1": case(**bad)}, tmp_path)
    assert any(needle in p for p in problems), problems


def test_missing_photo_is_reported(tmp_path):
    assert any("missing or empty" in p for p in validate_manifest({"c1": case()}, tmp_path))


# ---------------------------------------------------------------- line items

TRUTH = [
    {"product_name": "Tata Salt 1kg", "quantity": 20, "unit": "pkt", "purchase_price": 22.0, "mrp": 28.0,
     "printed_amount": 440.0},
    {"product_name": "MDH Jeera Powder 100g", "quantity": 12, "unit": "pcs", "purchase_price": 58.75, "mrp": None,
     "printed_amount": 705.0},
]


def test_fully_correct_requires_name_qty_rate_and_amount():
    got = [dict(TRUTH[0]), {**TRUTH[1], "printed_amount": 700.0}]
    s = score_items(got, TRUTH)
    assert s["fully_correct"] == 1 and s["partially_correct"] == 1
    assert s["fields"]["printed_amount"] == {"evaluated": 2, "correct": 1, "invented": 0}


def test_name_only_is_partial_never_full():
    got = [{"product_name": "Tata Salt 1kg"}]
    s = score_items(got, TRUTH[:1])
    assert (s["fully_correct"], s["partially_correct"], s["lines_found"]) == (0, 1, 1)


def test_values_for_unprinted_fields_count_as_invented():
    got = [dict(TRUTH[0]), {**TRUTH[1], "mrp": 58.75}]  # MRP not printed, rate copied into it
    s = score_items(got, TRUTH)
    assert s["fields"]["mrp"] == {"evaluated": 1, "correct": 1, "invented": 1}


def test_units_compared_without_conversion():
    s = score_items([{**TRUTH[0], "unit": "kg"}], TRUTH[:1])
    assert s["fields"]["unit"]["correct"] == 0
    s = score_items([{**TRUTH[0], "unit": "PKT"}], TRUTH[:1])
    assert s["fields"]["unit"]["correct"] == 1


def test_ambiguous_fields_are_not_scored():
    truth = [{**TRUTH[1], "ambiguous": ["printed_amount"]}]
    s = score_items([{**TRUTH[1], "printed_amount": 1.0}], truth)
    assert s["fields"]["printed_amount"]["evaluated"] == 0 and s["fully_correct"] == 1


def test_decimal_corruption_is_detected_and_reported():
    s = score_items([dict(TRUTH[0]), {**TRUTH[1], "purchase_price": 58575.0}], TRUTH)
    assert s["decimal_corruption"] == [{"product": "MDH Jeera Powder 100g", "field": "purchase_price",
                                        "expected": 58.75, "got": 58575.0, "kind": "decimal point read as a digit"}]


@pytest.mark.parametrize("truth,got,kind", [
    (58.75, 58575, "decimal point read as a digit"),
    (58.75, 5875, "decimal shifted by 10^2"),
    (0.85, 85, "decimal shifted by 10^2"),
    (245.0, 2450, "decimal shifted by 10^1"),
    (58.75, 58.75, None),
    (58.75, 60.0, None),
    (None, 5, None),
])
def test_decimal_corruption_kinds(truth, got, kind):
    assert decimal_corruption(truth, got) == kind


def test_extra_and_missing_lines_counted():
    s = score_items([{"product_name": "Something Else", "quantity": 1}], TRUTH)
    assert s["lines_found"] == 0 and s["extra_lines"] == 1 and s["fully_correct"] == 0


# ---------------------------------------------------------------- header

def test_header_states():
    truth = {"supplier_name": "Sri Lakshmi Wholesale Traders", "invoice_number": "INV-00427", "invoice_date": None}
    got = {"supplier_name": "SRI LAKSHMI WHOLESALE TRADERS", "invoice_number": "inv-00427", "invoice_date": "17/11/2026"}
    assert score_header(got, truth) == {"supplier_name": "correct", "invoice_number": "correct",
                                        "invoice_date": "invented"}
    assert score_header({}, truth) == {"supplier_name": "missed", "invoice_number": "missed",
                                       "invoice_date": "correct_empty"}
    assert score_header({"invoice_date": "2026-10-08"}, {"invoice_date": "08/10/2026"})["invoice_date"] == "correct"
    assert score_header({"supplier_name": "Item Description Qty"}, {"supplier_name": "Balaji Traders"})["supplier_name"] == "wrong"
    assert score_header({}, None) == {f: "not_recorded" for f in ("supplier_name", "invoice_number", "invoice_date")}
