"""
Grand-total reconciliation (Phase 3A, C2) - a warning-only safeguard.

The extracted line amounts are compared with the total printed on the invoice. Invoice-level
adjustments that are printed (round off, freight / other charges, total tax when line amounts are
before tax, discounts / credit adjustments, TCS) are taken into account. Nothing is ever changed:
a mismatch produces a warning for the reviewer, plus - when one or two line amounts with a lost
decimal point (x10, x100, x1000) explain the difference exactly - a suggestion on those lines.
When the printed total cannot be identified reliably, the result says reconciliation could not be
completed. An invoice is never rejected because of a mismatch.

All arithmetic is Decimal.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence, Tuple
from services.money import format_rupees

# Labels that name the final payable total of the whole invoice
_TOTAL_LABEL = re.compile(
    r"\b(?:grand\s*total|net\s*payable|net\s*amount\s*payable|net\s*amount|netamount|amount\s*payable|"
    r"total\s*payable|invoice\s*(?:total|value|amount)|bill\s*amount|net\s*bill(?:\s*amount)?|"
    r"total\s*amount\s*payable)\b",
    re.I,
)
# Lines that only look like totals: quantities, counts, tax/discount sub-totals, amount in words
_NOT_A_TOTAL = re.compile(
    r"\b(?:qty|quantity|units?|items?|cases|pcs|kgs?|tax|gst|cgst|sgst|igst|cess|discount|disc|scheme|"
    r"words|rupees|taxable|gross|sub\s*total|page\s*total|saving|you\s*saved)\b",
    re.I,
)
_ADJUSTMENTS: Sequence[Tuple[str, re.Pattern, int]] = (
    ("round_off", re.compile(r"\bround(?:ing)?\s*(?:off|adj\w*)?\b|\br\s*/\s*o\b", re.I), 0),  # sign as printed
    ("charges", re.compile(r"\b(?:freight|transport|delivery|packing|handling|courier|other\s*charges|"
                           r"add(?:itional)?\s*(?:value|charges?)|total\s*addition)\b", re.I), +1),
    ("tax", re.compile(r"\b(?:total\s*tax|tax\s*amount|tax\s*amt|total\s*gst|gst\s*(?:amount|value))\b", re.I), +1),
    ("tcs", re.compile(r"\btcs\b", re.I), +1),
    ("discount", re.compile(r"\b(?:total\s*discount|cash\s*disc\w*|other\s*disc\w*|total\s*deduction|"
                            r"special\s*disc\w*|less\s*:?\s*disc\w*)\b", re.I), -1),
    ("credit", re.compile(r"\b(?:credit\s*(?:note|adj\w*)|crn\s*adj\w*|debit\s*adj\w*)\b", re.I), -1),
)
_NUM = re.compile(r"(?<![\w.])-?\(?₹?\s*\d[\d,]*(?:\.\d{1,3})?\)?(?![\w.])")


def _to_dec(text: str) -> Optional[Decimal]:
    t = text.strip()
    negative = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = re.sub(r"[^\d.]", "", t)
    if not t or t.count(".") > 1:
        return None
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    return -v if negative else v


def _money_values(line: str) -> List[Decimal]:
    out = []
    for m in _NUM.finditer(line):
        v = _to_dec(m.group(0))
        if v is not None:
            out.append(v)
    return out


@dataclass
class PrintedTotals:
    total: Optional[Decimal] = None
    total_label: Optional[str] = None
    reliable: bool = False
    reason: str = ""
    candidates: List[Tuple[str, Decimal]] = field(default_factory=list)
    adjustments: Dict[str, Decimal] = field(default_factory=dict)


def find_printed_totals(lines: Sequence[str]) -> PrintedTotals:
    """Locate the printed grand total and the printed invoice-level adjustments.

    The total is reliable only when every candidate with a final-total label agrees (one value).
    A label line without a number takes the number on the next line when that line is only a number.
    """
    res = PrintedTotals()
    clean = [ln.strip() for ln in lines if ln and ln.strip()]
    for i, ln in enumerate(clean):
        m = _TOTAL_LABEL.search(ln)
        if m and not _NOT_A_TOTAL.search(ln[: m.start()] + " " + ln[m.end():m.end() + 3]):
            after = ln[m.end():]
            vals = [v for v in _money_values(after) if v > 0]
            if not vals and i + 1 < len(clean) and re.fullmatch(r"[\s:₹rs.\-]*\d[\d,]*(?:\.\d{1,3})?[\s|]*", clean[i + 1], re.I):
                vals = [v for v in _money_values(clean[i + 1]) if v > 0]
            if vals:
                res.candidates.append((m.group(0), vals[-1]))
        for name, pat, _sign in _ADJUSTMENTS:
            am = pat.search(ln)
            if not am or _TOTAL_LABEL.search(ln):
                continue
            vals = _money_values(ln[am.end():])
            if vals and name not in res.adjustments:
                res.adjustments[name] = vals[-1]
    values = sorted({v for _, v in res.candidates})
    if not values:
        res.reason = "No printed grand total (Grand Total / Net Amount / Amount Payable) was found."
    elif len(values) > 1:
        res.reason = ("Several different totals are printed or were read (" +
                      ", ".join(_rs(v) for v in values) + "); the grand total is not certain.")
    else:
        res.total, res.reliable = values[0], True
        res.total_label = next(lbl for lbl, v in res.candidates if v == values[0])
    return res


def _rs(v: Decimal) -> str:
    """₹1,234.50 / ₹62.988 (a printed third decimal is kept; half-up, shared money formatter)."""
    return format_rupees(v)


def _tolerance(total: Decimal) -> Decimal:
    return max(Decimal("1.00"), (total * Decimal("0.001")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _explain(lines_total: Decimal, printed: Decimal, adj: Dict[str, Decimal]) -> Optional[Tuple[List[str], Decimal]]:
    """Smallest set of printed adjustments that reconciles the line total with the printed total."""
    signs = {name: sign for name, _, sign in _ADJUSTMENTS}
    names = [n for n in adj if adj[n] != 0]
    tol = _tolerance(printed)
    for k in range(0, len(names) + 1):
        for combo in itertools.combinations(names, k):
            expected = lines_total
            for n in combo:
                v = adj[n]
                expected += v if signs[n] == 0 else signs[n] * abs(v)
            if abs(expected - printed) <= tol:
                return list(combo), expected
    return None


def reconcile_invoice_total(lines: Sequence[str], line_amounts: Sequence[Optional[Decimal]]) -> Dict[str, Any]:
    """Compare the line amounts with the printed grand total (warning-only).

    Returns a JSON-safe dict: status ("matched" | "mismatch" | "not_completed"), message, printed
    total, line total, difference, adjustments used, and `line_suggestions` {index: text} for lines
    whose lost decimal point would explain the difference exactly.
    """
    printed = find_printed_totals(lines)
    amounts = [a for a in line_amounts if a is not None]
    out: Dict[str, Any] = {
        "status": "not_completed",
        "printed_total": float(printed.total) if printed.total is not None else None,
        "printed_total_label": printed.total_label,
        "lines_total": None,
        "difference": None,
        "adjustments_found": {k: float(v) for k, v in printed.adjustments.items()},
        "adjustments_used": [],
        "line_suggestions": {},
        "message": "",
    }
    if not amounts:
        out["message"] = "Reconciliation could not be completed: no line amounts were read."
        return out
    lines_total = sum(amounts, Decimal("0"))
    out["lines_total"] = float(lines_total)
    if not printed.reliable or printed.total is None:
        out["message"] = f"Reconciliation could not be completed: {printed.reason}"
        return out
    total = printed.total
    explained = _explain(lines_total, total, printed.adjustments)
    if explained is not None:
        used, expected = explained
        out.update(status="matched", adjustments_used=used, difference=float(total - expected))
        out["message"] = (f"Line amounts agree with the printed total {_rs(total)}"
                          + (f" (with {', '.join(u.replace('_', ' ') for u in used)})" if used else "") + ".")
        return out

    diff = total - lines_total
    out.update(status="mismatch", difference=float(diff))
    out["message"] = (f"The line amounts add up to {_rs(lines_total)} but the invoice total is {_rs(total)} "
                      f"(difference {_rs(diff)}). Please check the line amounts before adding to stock.")
    # One or two line amounts with a lost decimal point that would explain the difference exactly
    idx_amounts = [(i, a) for i, a in enumerate(line_amounts) if a is not None and a > 0]
    factors = (Decimal("10"), Decimal("100"), Decimal("1000"))
    for k in (1, 2):
        for combo in itertools.combinations(idx_amounts, k):
            for fs in itertools.product(factors, repeat=k):
                fixed = lines_total - sum(a for _, a in combo) + sum(a / f for (_, a), f in zip(combo, fs))
                if _explain(fixed, total, printed.adjustments) is not None:
                    for (i, a), f in zip(combo, fs):
                        out["line_suggestions"][i] = (
                            f"Line amount {_rs(a)} may be {_rs(a / f)} (decimal point lost): with it, the "
                            f"lines add up to the printed total {_rs(total)}. Please check quantity and amount.")
                    return out
    return out
