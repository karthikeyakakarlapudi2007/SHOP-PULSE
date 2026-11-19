"""
Shared Decimal money rules (Phase 4, workstream 4). The backend is authoritative for financial values.

Approved rules:
  * Money is calculated in Decimal, built from strings (``Decimal(str(x))``), never from a binary float.
  * Currency rounding is always ROUND_HALF_UP (1.005 -> 1.01, 2.675 -> 2.68, 0.125 -> 0.13).
  * No intermediate rounding: round once, at the defined boundary.
  * Purchase values keep printed precision up to 3 decimals (62.988 stays 62.988).
  * A sale line = quantity x unit price, rounded to 2 dp; a bill = sum of the rounded lines.
  * JSON responses keep plain numbers: Decimal -> float only at the API / storage boundary, after rounding.

The invoice service's helpers ``_dec``, ``_money``, ``_num`` and ``_keep_printed_precision`` now live here
(``services/invoice.py`` imports them under their old names).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Optional

ROUNDING = ROUND_HALF_UP
CURRENCY = Decimal("0.01")
PRICE = Decimal("0.001")
ZERO = Decimal("0")


def to_decimal(value: Any) -> Optional[Decimal]:
    """Decimal from Decimal / int / float / str (floats through their shortest repr: 0.1 -> 0.1).

    None, "", booleans, unparsable text and NaN / infinity give None.
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def quantize_half_up(value: Decimal, places: Any = CURRENCY) -> Decimal:
    """Round half-up to ``places`` (a Decimal exponent such as 0.01, or its string)."""
    return value.quantize(Decimal(places) if not isinstance(places, Decimal) else places, rounding=ROUNDING)


def round_currency(value: Decimal) -> Decimal:
    """Final currency amount: 2 dp, half-up."""
    return quantize_half_up(value, CURRENCY)


def round_price(value: Decimal) -> Decimal:
    """Unit price for display / storage: 3 dp, half-up."""
    return quantize_half_up(value, PRICE)


def keep_printed_precision(value: Decimal) -> Decimal:
    """Up to 3 decimals, as printed (62.988 stays 62.988, 560.5 stays 560.50); never rounded to paise."""
    v3 = quantize_half_up(value, PRICE)
    as_2dp = v3.quantize(CURRENCY, rounding=ROUNDING)
    return v3 if v3 != as_2dp else as_2dp


def sum_decimal(values: Iterable[Any]) -> Decimal:
    """Exact sum; None and unparsable values are skipped."""
    total = ZERO
    for v in values:
        d = to_decimal(v)
        if d is not None:
            total += d
    return total


def sale_line_amount(quantity: Any, unit_price: Any) -> Decimal:
    """Sale line: quantity x unit price (unrounded), then rounded once to 2 dp half-up."""
    q, p = to_decimal(quantity), to_decimal(unit_price)
    if q is None or p is None:
        raise ValueError(f"Sale line needs a numeric quantity and unit price, got {quantity!r} x {unit_price!r}")
    return round_currency(q * p)


def bill_total(line_amounts: Iterable[Decimal]) -> Decimal:
    """Bill = sum of the already-rounded line amounts (never re-rounded as a whole)."""
    return sum(line_amounts, ZERO)


def to_number(value: Optional[Decimal]) -> Optional[float]:
    """JSON / storage boundary: a rounded Decimal as a plain number (exact for <= 15 significant digits)."""
    return float(value) if value is not None else None


def format_rupees(value: Any) -> str:
    """'₹1,234.50', or '₹51.996' when a third decimal is printed. Half-up, never float formatting."""
    d = to_decimal(value)
    if d is None:
        return "₹—"
    shown = keep_printed_precision(d)
    places = 3 if shown != shown.quantize(CURRENCY, rounding=ROUNDING) else 2
    return f"₹{shown:,.{places}f}"
