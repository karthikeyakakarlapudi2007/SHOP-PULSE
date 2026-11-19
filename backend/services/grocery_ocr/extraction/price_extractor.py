"""
Price and financial value extraction interface and implementation.
Extracts monetary rates, MRP, discounts, taxes, and printed line amounts.
Strictly relies on column roles and geometric evidence; never infers financial role from numeric magnitude.
Preserves Python Decimal throughout; never defaults missing prices to zero.
"""

import re
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from services.grocery_ocr.config import GroceryOCRConfig, default_config
from services.grocery_ocr.exceptions import ExtractionError
from services.grocery_ocr.extraction.numeric_parser import NumericParser
from services.grocery_ocr.logger import get_logger
from services.grocery_ocr.schemas.table import DetectedColumn, TableRow

logger = get_logger("extraction.price_extractor")

_MONEY_RE = re.compile(r"^(?:₹|rs\.?)?\s*-?\d{1,3}(?:,\d{2,3})*(?:\.\d{2,3})$|^(?:₹|rs\.?)?\s*-?\d+\.\d{2,3}$", re.I)


# Columns whose cells may supply a unit price by position (when price headings were not read)
_PRICE_SOURCE_ROLES = {"unknown", "rate", "purchase_price", "selling_price", "mrp"}


def is_money_like(text: str) -> bool:
    """A printed money value: digits with a decimal point and 2-3 decimals ('245.00', '1,378.62',
    '62.988'). Integers (HSN codes, units per case, serial numbers, GST %) are not money-like."""
    # Table-rule artefacts around a cell value ('960.00 |', '[245.00') are not part of the number
    cleaned = re.sub(r"^[\s|\[\](){}]+|[\s|\[\](){}]+$", "", (text or "")).rstrip("/-").strip()
    return bool(_MONEY_RE.match(cleaned))


def tax_component(header: str) -> str:
    """Name a tax column by its printed heading: cgst_amount, sgst_amount (SGST or UTGST),
    igst_amount, cess_amount, else tax_amount."""
    h = (header or "").lower().replace(" ", "")
    if "cgst" in h:
        return "cgst_amount"
    if "sgst" in h or "utgst" in h or "s/ut" in h:
        return "sgst_amount"
    if "igst" in h:
        return "igst_amount"
    if "cess" in h:
        return "cess_amount"
    return "tax_amount"


def discount_component(header: str) -> str:
    """Name a discount column by its printed heading: scheme_discount, cash_discount, trade_discount,
    else other_discount (e.g. 'RS Disc')."""
    h = (header or "").lower()
    if "sch" in h:
        return "scheme_discount"
    if "cash" in h or re.search(r"\bcd\b", h):
        return "cash_discount"
    if "trade" in h or re.search(r"\btd\b", h):
        return "trade_discount"
    return "other_discount"


def _unique(existing: Dict[str, Decimal], label: str) -> str:
    if label not in existing:
        return label
    n = 2
    while f"{label}_{n}" in existing:
        n += 1
    return f"{label}_{n}"


class FinancialExtractionResult(BaseModel):
    """Detailed result of extracting financial values from an invoice row."""
    purchase_price: Optional[Decimal] = Field(None, description="Purchase rate per unit")
    selling_price: Optional[Decimal] = Field(None, description="Selling price per unit")
    mrp: Optional[Decimal] = Field(None, description="Maximum Retail Price (MRP)")
    discount: Optional[Decimal] = Field(None, description="Discount amount")
    discount_pct: Optional[Decimal] = Field(None, description="Discount percentage")
    tax_amount: Optional[Decimal] = Field(None, description="Tax / GST amount")
    gst_rate: Optional[Decimal] = Field(None, description="GST rate percentage")
    taxable_amount: Optional[Decimal] = Field(None, description="Taxable amount before tax")
    printed_amount: Optional[Decimal] = Field(None, description="Printed line total amount")

    # Audit & Provenance
    raw_financial_cells: Dict[str, str] = Field(default_factory=dict, description="Verbatim raw text per field")
    financial_role_confidence: Dict[str, float] = Field(default_factory=dict, description="Confidence per role assignment")
    is_ambiguous_rate: bool = Field(default=False, description="True if column was generic RATE without role clarification")
    issues: List[str] = Field(default_factory=list, description="Audit issues encountered during extraction")
    components: Dict[str, Decimal] = Field(
        default_factory=dict,
        description="Separately printed parts: cgst_amount, sgst_amount, igst_amount, cess_amount, "
                    "scheme_discount, other_discount, ... (and their rates when several GST % columns exist)")
    review_reasons: List[str] = Field(default_factory=list, description="Reasons this line needs manual review")
    suggestions: List[str] = Field(default_factory=list, description="Possible readings for the reviewer (never applied)")


class IPriceExtractor(ABC):
    """Abstract interface for extracting financial price and total fields from table rows."""

    @abstractmethod
    def extract_prices(
        self,
        row: TableRow,
        columns: List[DetectedColumn],
    ) -> Dict[str, Optional[Decimal]]:
        """
        Extracts all price columns as Decimal values.

        Returns:
            Dict containing 'purchase_price', 'selling_price', 'mrp', 'discount',
            'tax_amount', 'gst_rate', 'printed_amount', etc. Missing values are None.
        """
        pass

    @abstractmethod
    def extract_financials_detailed(
        self,
        row: TableRow,
        columns: List[DetectedColumn],
    ) -> FinancialExtractionResult:
        """
        Extracts financial values with complete audit telemetry and confidence metrics.
        """
        pass


class BasePriceExtractor(IPriceExtractor):
    """
    Standard financial extractor.
    Enforces column-role mapping safety and Decimal arithmetic.
    """

    def __init__(self, config: Optional[GroceryOCRConfig] = None):
        self.config = config or default_config
        self.numeric_parser = NumericParser(self.config)

    def extract_prices(
        self,
        row: TableRow,
        columns: List[DetectedColumn],
    ) -> Dict[str, Optional[Decimal]]:
        res = self.extract_financials_detailed(row, columns)
        return {
            "purchase_price": res.purchase_price,
            "selling_price": res.selling_price,
            "mrp": res.mrp,
            "discount": res.discount,
            "discount_pct": res.discount_pct,
            "tax_amount": res.tax_amount,
            "gst_rate": res.gst_rate,
            "taxable_amount": res.taxable_amount,
            "printed_amount": res.printed_amount,
        }

    def extract_financials_detailed(
        self,
        row: TableRow,
        columns: List[DetectedColumn],
    ) -> FinancialExtractionResult:
        try:
            result = FinancialExtractionResult()
            rate_columns = [c for c in columns if c.role in ("rate", "purchase_price")]
            is_generic_rate = any("rate" in c.header_text.lower() and "purchase" not in c.header_text.lower() for c in rate_columns)
            tax_parts: Dict[str, Decimal] = {}
            gst_parts: Dict[str, Decimal] = {}
            disc_parts: Dict[str, Decimal] = {}

            for col in columns:
                if col.column_index >= len(row.cells):
                    continue

                raw_cell = row.cells[col.column_index].cleaned_text.strip()
                if not raw_cell:
                    continue

                parsed = self.numeric_parser.parse_currency(raw_cell)
                if not parsed.is_valid or parsed.value is None:
                    continue

                val = parsed.value
                conf = parsed.confidence * (col.confidence / 100.0)

                if col.role in ("rate", "purchase_price") and result.purchase_price is None:
                    result.purchase_price = val
                    result.raw_financial_cells["purchase_price"] = raw_cell
                    # If inferred from generic RATE header, reflect in confidence
                    if is_generic_rate:
                        result.financial_role_confidence["purchase_price"] = min(conf, 75.0)
                        result.is_ambiguous_rate = True
                        result.issues.append("Rate column does not explicitly specify Purchase vs Selling price")
                    else:
                        result.financial_role_confidence["purchase_price"] = conf

                elif col.role == "selling_price" and result.selling_price is None:
                    result.selling_price = val
                    result.raw_financial_cells["selling_price"] = raw_cell
                    result.financial_role_confidence["selling_price"] = conf

                elif col.role == "mrp" and result.mrp is None:
                    result.mrp = val
                    result.raw_financial_cells["mrp"] = raw_cell
                    result.financial_role_confidence["mrp"] = conf

                elif col.role == "discount":
                    if col.is_percent or parsed.is_percentage or "%" in raw_cell:
                        if result.discount_pct is None:
                            result.discount_pct = val
                            result.raw_financial_cells["discount_pct"] = raw_cell
                            result.financial_role_confidence["discount_pct"] = conf
                    else:
                        # Every discount column is kept (scheme, RS / trade, cash ...); never overwritten
                        label = _unique(disc_parts, discount_component(col.header_text))
                        disc_parts[label] = val
                        result.raw_financial_cells[label] = raw_cell
                        result.financial_role_confidence["discount"] = conf

                elif col.role == "discount_pct" and result.discount_pct is None:
                    result.discount_pct = val
                    result.raw_financial_cells["discount_pct"] = raw_cell
                    result.financial_role_confidence["discount_pct"] = conf

                elif col.role == "tax_amount":
                    # CGST, SGST/UTGST, IGST and cess columns are kept separately
                    label = _unique(tax_parts, tax_component(col.header_text))
                    tax_parts[label] = val
                    result.raw_financial_cells[label] = raw_cell
                    result.financial_role_confidence["tax_amount"] = conf

                elif col.role == "gst_rate":
                    label = _unique(gst_parts, tax_component(col.header_text).replace("_amount", "_rate"))
                    gst_parts[label] = val
                    result.raw_financial_cells[label] = raw_cell
                    result.financial_role_confidence["gst_rate"] = conf

                elif col.role == "taxable" and result.taxable_amount is None:
                    result.taxable_amount = val
                    result.raw_financial_cells["taxable_amount"] = raw_cell
                    result.financial_role_confidence["taxable_amount"] = conf

                elif col.role == "total" and result.printed_amount is None:
                    result.printed_amount = val
                    result.raw_financial_cells["printed_amount"] = raw_cell
                    result.financial_role_confidence["printed_amount"] = conf

            if disc_parts:
                result.discount = sum(disc_parts.values(), Decimal("0"))
                result.components.update(disc_parts)
            if tax_parts:
                split = {k: v for k, v in tax_parts.items() if not k.startswith("tax_amount")}
                generic = [v for k, v in tax_parts.items() if k.startswith("tax_amount")]
                result.tax_amount = sum(split.values(), Decimal("0")) if split else generic[0]
                result.components.update(tax_parts)
                if split and generic and abs(generic[0] - result.tax_amount) > Decimal("0.05"):
                    result.review_reasons.append(
                        f"Tax columns disagree: components total ₹{result.tax_amount} but tax column shows ₹{generic[0]}")
            if gst_parts:
                split = {k: v for k, v in gst_parts.items() if k in ("cgst_rate", "sgst_rate")}
                # CGST % + SGST % is the GST rate; a single GST % / IGST % column is used as printed
                result.gst_rate = (sum(split.values(), Decimal("0")) if len(split) == 2
                                   else next(iter(gst_parts.values())))
                if len(gst_parts) > 1:
                    result.components.update(gst_parts)

            role_of_cell = {c.column_index: c.role for c in columns}

            # Fallback when no amount column was read: only a money-shaped value (with a decimal
            # point) in a column that has NO identified role may be used, and the line is flagged.
            # HSN codes, serial numbers, quantities, units per case, GST % and tax / discount /
            # taxable / price columns are never taken as the line amount.
            if result.printed_amount is None and row.cells:
                for idx in range(len(row.cells) - 1, -1, -1):
                    c = row.cells[idx]
                    txt = c.cleaned_text.strip()
                    if role_of_cell.get(idx, "unknown") != "unknown" or not is_money_like(txt):
                        continue
                    parsed_trailing = self.numeric_parser.parse_currency(txt)
                    if parsed_trailing.is_valid and parsed_trailing.value is not None and parsed_trailing.value > 0:
                        result.printed_amount = parsed_trailing.value
                        result.raw_financial_cells["printed_amount"] = txt
                        result.financial_role_confidence["printed_amount"] = 60.0
                        result.review_reasons.append(
                            f"Line amount ₹{parsed_trailing.value} was taken from a column without an "
                            "Amount heading; please check it")
                        break

            # Multi-price reconciliation from unlabelled or price columns only (never from qty / HSN /
            # tax / discount / taxable / amount columns), and always flagged for review.
            if result.purchase_price is None or result.selling_price is None or result.mrp is None:
                p_cells = []
                for idx, c in enumerate(row.cells):
                    txt = c.cleaned_text.strip()
                    if (not txt or not c.bbox or role_of_cell.get(idx, "unknown") not in _PRICE_SOURCE_ROLES
                            or not is_money_like(txt)):
                        continue
                    parsed_p = self.numeric_parser.parse_currency(txt)
                    if parsed_p.is_valid and parsed_p.value is not None and parsed_p.value > 0:
                        p_cells.append((c.bbox.x0, parsed_p.value, txt))
                p_cells.sort(key=lambda x: x[0])
                if len(p_cells) >= 3:
                    for i in range(len(p_cells) - 2):
                        p1, p2, p3 = p_cells[i][1], p_cells[i + 1][1], p_cells[i + 2][1]
                        if p1 <= p2 <= p3 and (result.printed_amount is None or p3 != result.printed_amount):
                            assigned = []
                            if result.purchase_price is None:
                                result.purchase_price = p1
                                result.raw_financial_cells["purchase_price"] = p_cells[i][2]
                                assigned.append("rate")
                            if result.selling_price is None:
                                result.selling_price = p2
                                result.raw_financial_cells["selling_price"] = p_cells[i + 1][2]
                                assigned.append("selling price")
                            if result.mrp is None:
                                result.mrp = p3
                                result.raw_financial_cells["mrp"] = p_cells[i + 2][2]
                                assigned.append("MRP")
                            if assigned:
                                result.review_reasons.append(
                                    f"{', '.join(assigned)} assigned by position from unlabelled columns; please check")
                            break

            # A selling price or MRP far above the rate may have lost its decimal point. The printed
            # value is kept; the possible reading is only suggested for review (never applied).
            if result.selling_price is not None and result.selling_price > 0:
                ref = result.mrp if result.mrp is not None else result.purchase_price
                if ref is not None and ref > 0 and result.selling_price > ref * 5:
                    result.suggestions.append(
                        f"Selling price ₹{result.selling_price} may be ₹{result.selling_price / Decimal('100')} "
                        "(decimal point lost); please check")
                    result.review_reasons.append("Selling price is unusually high compared with the rate/MRP")
            if result.mrp is not None and result.purchase_price is not None and result.purchase_price > 0 \
                    and result.mrp > result.purchase_price * 5:
                candidate_mrp = result.mrp / Decimal("100")
                if result.purchase_price * Decimal("0.8") <= candidate_mrp <= result.purchase_price * Decimal("3.0"):
                    result.suggestions.append(
                        f"MRP ₹{result.mrp} may be ₹{candidate_mrp} (decimal point lost); please check")
                    result.review_reasons.append("MRP is unusually high compared with the rate")

            return result

        except Exception as exc:
            logger.error("Price extraction failed on row %d: %s", row.row_index, exc)
            raise ExtractionError(f"Failed to extract prices: {exc}", details={"row": row.row_index})
