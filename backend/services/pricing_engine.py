"""
Universal Decimal Pricing Engine for ShopPulse (Stage 1).

Authoritative server-side calculation engine for universal product pricing, unit normalization,
and line total calculations. Follows strict Decimal arithmetic and ROUND_HALF_UP currency rules.

Core Formula:
    LINE TOTAL = (NORMALIZED REQUESTED QUANTITY / PRICING BASIS QUANTITY) * CATALOG SELLING PRICE

Rules:
  * Calculations are strictly in Python Decimal. Binary floating-point arithmetic is never used.
  * Currency amounts are rounded once to paise (Decimal('0.01')) using ROUND_HALF_UP.
  * Inputs are converted safely from Decimal / int / float / str using string representation.
  * Booleans, NaN, Infinity, negative quantities, zero quantities, and invalid numbers are rejected.
  * Unit conversions only occur within compatible families (mass: kg <-> g, volume: L <-> ml, count: dozen <-> pcs).
  * Across-family conversions (e.g. box -> pcs) strictly require explicit ProductUnitConversion.
  * Package sizes and multipliers are never invented or silently assumed.
  * Purchase cost, selling price, and MRP are kept semantically separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Sequence, Union

from services.money import (
    CURRENCY,
    PRICE,
    ROUNDING,
    quantize_half_up,
    round_currency,
    round_price,
    to_number,
)
from services.unit_registry import (
    ProductUnitConversion,
    UnitError,
    UnknownUnitError,
    convert_quantity,
    get_unit,
    normalize_unit,
    validate_quantity_unit,
    are_units_compatible,
    get_base_unit,
)

# ----------------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------------


class PricingEngineError(ValueError):
    """Base exception for all pricing engine errors (subclasses ValueError for caller compatibility)."""


class InvalidQuantityError(PricingEngineError):
    """Raised when quantity is invalid, non-numeric, non-finite, zero, or negative."""


class InvalidPriceError(PricingEngineError):
    """Raised when price is invalid, non-numeric, non-finite, or negative."""


class InvalidPricingBasisError(PricingEngineError):
    """Raised when pricing basis quantity is <= 0 or basis unit is invalid."""


class IncompatiblePricingUnitsError(PricingEngineError):
    """Raised when requested unit cannot be converted to pricing basis or inventory unit."""


class PriceAssertionError(PricingEngineError):
    """Raised when client-supplied unit_price assertion fails to match authoritative catalog rate."""


class PricingStatusError(PricingEngineError):
    """Raised when attempting to sell a product whose status is not approved for retail checkout."""


class MrpExceededError(PricingEngineError):
    """Raised when selling price exceeds statutory Maximum Retail Price (MRP)."""


# ----------------------------------------------------------------------------
# Result Data Structures
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class LinePricingResult:
    """Immutable result of a server-authoritative line pricing calculation."""

    line_total: Decimal
    """Final line total in rupees rounded to 2 decimal places (paise) with ROUND_HALF_UP."""

    unrounded_line_total: Decimal
    """Exact Decimal line total before paise rounding."""

    effective_unit_price: Decimal
    """Unit rate per single unit of pricing_basis_unit, rounded to 3 decimal places with ROUND_HALF_UP."""

    normalized_quantity: Decimal
    """Requested quantity converted into the pricing_basis_unit."""

    pricing_basis_quantity: Decimal
    """Reference quantity for which the catalog selling price is quoted (e.g. 1.0, 100.0, 12.0)."""

    pricing_basis_unit: str
    """Canonical unit id in which the pricing basis is quoted (e.g. 'kg', 'g', 'pcs')."""

    requested_quantity: Decimal
    """Original requested quantity as an exact Decimal."""

    requested_unit: str
    """Canonical unit id of the requested quantity."""

    stock_deduction_quantity: Decimal
    """Quantity to deduct from physical inventory, expressed in the inventory_unit."""

    inventory_unit: str
    """Canonical physical inventory tracking unit (e.g. 'kg', 'pcs', 'L')."""

    is_wholesale_only: bool = False
    """Whether the item is restricted to whole-container wholesale checkout."""

    line_mrp_total: Optional[Decimal] = None
    """Statutory MRP ceiling for this line, if applicable."""

    savings_amount: Optional[Decimal] = None
    """Customer savings compared to statutory MRP ceiling (MRP - line total)."""

    @property
    def line_total_float(self) -> float:
        """Helper for JSON / API responses."""
        return float(self.line_total)

    @property
    def effective_unit_price_float(self) -> float:
        return float(self.effective_unit_price)

    @property
    def stock_deduction_float(self) -> float:
        return float(self.stock_deduction_quantity)


@dataclass(frozen=True)
class PurchaseCostResult:
    """Normalized purchase / procurement cost result."""

    unit_cost: Decimal
    """Procurement cost per single unit of price_basis_unit (rounded to 3 dp)."""

    line_cost: Decimal
    """Total procurement cost for the requested quantity (rounded to 2 dp)."""

    pricing_basis_quantity: Decimal
    pricing_basis_unit: str
    normalized_quantity: Decimal


@dataclass(frozen=True)
class MrpCeilingResult:
    """Statutory Maximum Retail Price ceiling evaluation."""

    mrp_per_basis: Optional[Decimal]
    """Statutory MRP ceiling per pricing basis (None for loose commodities)."""

    line_mrp_total: Optional[Decimal]
    """Total MRP ceiling for the requested quantity (None for loose commodities)."""

    is_exceeded: bool
    """True if selling price exceeds statutory MRP ceiling."""

    savings_amount: Optional[Decimal]
    """Consumer savings (line_mrp_total - line_total), or None if loose."""

    effective_sp_rate: Optional[Decimal] = None
    """Effective selling rate per single canonical base unit."""

    effective_mrp_rate: Optional[Decimal] = None
    """Effective MRP rate per single canonical base unit."""


# ----------------------------------------------------------------------------
# Validation and Decimal Normalization
# ----------------------------------------------------------------------------


def to_exact_decimal(val: Any, name: str = "Value") -> Decimal:
    """Convert input safely to a finite Decimal.

    Rejects booleans, None, empty strings, unparsable text, NaN, and Infinity.
    Floats are converted through str(val) to avoid binary floating-point drift.
    """
    if val is None or isinstance(val, bool) or val == "":
        raise PricingEngineError(f"{name} must be a valid number, got {val!r}")
    if isinstance(val, Decimal):
        if not val.is_finite():
            raise PricingEngineError(f"{name} must be a finite number, got {val}")
        return val
    try:
        d = Decimal(str(val).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise PricingEngineError(f"{name} is not a valid number: {val!r}") from None
    if not d.is_finite():
        raise PricingEngineError(f"{name} must be a finite number, got {val}")
    return d


def validate_quantity(quantity: Any, unit: Optional[str] = None, *, allow_zero: bool = False,
                      name: str = "Quantity") -> Decimal:
    """Ensure quantity is a finite, positive Decimal (or >= 0 if allow_zero=True)."""
    try:
        q = to_exact_decimal(quantity, name=name)
    except PricingEngineError as exc:
        raise InvalidQuantityError(str(exc)) from None

    if q < 0 or (q == 0 and not allow_zero):
        raise InvalidQuantityError(
            f"{name} must be {'0 or greater' if allow_zero else 'greater than 0'}, got {quantity}"
        )
    return q


def validate_price(price: Any, name: str = "Price") -> Decimal:
    """Ensure price is a finite, non-negative Decimal (>= 0)."""
    try:
        p = to_exact_decimal(price, name=name)
    except PricingEngineError as exc:
        raise InvalidPriceError(str(exc)) from None

    if p < 0:
        raise InvalidPriceError(f"{name} cannot be negative, got {price}")
    return p


# ----------------------------------------------------------------------------
# Universal Line Pricing Engine
# ----------------------------------------------------------------------------


def calculate_line_price(
    quantity: Any,
    requested_unit: Optional[str],
    selling_price: Any,
    price_basis_quantity: Any = Decimal("1.0"),
    price_basis_unit: Optional[str] = None,
    inventory_unit: Optional[str] = None,
    product_conversions: Optional[Sequence[ProductUnitConversion]] = None,
    client_unit_price: Optional[Any] = None,
    pricing_status: Optional[str] = None,
    product_name: Optional[str] = None,
    mrp: Optional[Any] = None,
    mrp_basis_quantity: Optional[Any] = None,
    mrp_basis_unit: Optional[str] = None,
) -> LinePricingResult:
    """Calculate server-authoritative line total and stock deduction for a product line.

    Core Formula:
        LINE TOTAL = (NORMALIZED REQUESTED QUANTITY / PRICING BASIS QUANTITY) * CATALOG SELLING PRICE

    Args:
        quantity: Requested quantity (> 0).
        requested_unit: Unit in which quantity is requested (e.g. 'g', 'kg', 'ml', 'pcs').
        selling_price: Catalog selling price for price_basis_quantity of price_basis_unit.
        price_basis_quantity: Reference quantity for selling_price (default 1.0, must be > 0).
        price_basis_unit: Reference unit for selling_price (defaults to inventory_unit or requested_unit).
        inventory_unit: Physical stock tracking unit (defaults to price_basis_unit).
        product_conversions: Optional explicit product-specific conversion factors (e.g. 1 box = 12 pcs).
        client_unit_price: Optional client display assertion; validated against catalog rate.
        pricing_status: Optional status ('VERIFIED', 'WHOLESALE_ONLY', 'NEEDS_REVIEW', 'INCOMPLETE').
        product_name: Optional product name for clear error messaging.

    Returns:
        LinePricingResult with rounded line total, effective unit price, and stock deduction.

    Raises:
        PricingStatusError: If product status is INCOMPLETE or NEEDS_REVIEW.
        InvalidQuantityError: If quantity is <= 0, non-numeric, or non-finite.
        InvalidPriceError: If selling_price is < 0, non-numeric, or non-finite.
        InvalidPricingBasisError: If price_basis_quantity is <= 0.
        IncompatiblePricingUnitsError: If units cannot be converted within their family.
        PriceAssertionError: If client_unit_price assertion fails to match server rate.
    """
    pname = product_name or "Product"

    # 1. Gate check pricing status
    if pricing_status is not None:
        norm_status = str(pricing_status).strip().upper()
        if norm_status == "INCOMPLETE":
            raise PricingStatusError(f"Product '{pname}' has incomplete pricing (₹0.00). Cannot be checked out.")
        if norm_status == "NEEDS_REVIEW":
            raise PricingStatusError(f"Product '{pname}' requires manager pricing review before checkout.")

    # 2. Validate price and quantity inputs
    price_d = validate_price(selling_price, name=f"Selling price for '{pname}'")
    qty_d = validate_quantity(quantity, name=f"Quantity for '{pname}'")

    try:
        basis_qty_d = validate_quantity(
            price_basis_quantity,
            name=f"Price basis quantity for '{pname}'",
        )
    except InvalidQuantityError as exc:
        raise InvalidPricingBasisError(str(exc)) from None

    if basis_qty_d <= 0:
        raise InvalidPricingBasisError(f"Price basis quantity for '{pname}' must be greater than 0, got {price_basis_quantity}")

    # 3. Canonicalize unit strings
    try:
        inv_unit_canon = normalize_unit(inventory_unit) if inventory_unit else None
    except UnknownUnitError as exc:
        raise PricingEngineError(f"Inventory unit for '{pname}': {exc}") from None

    try:
        basis_unit_canon = (
            normalize_unit(price_basis_unit)
            if price_basis_unit
            else (inv_unit_canon or (normalize_unit(requested_unit) if requested_unit else "pcs"))
        )
    except UnknownUnitError as exc:
        raise InvalidPricingBasisError(f"Price basis unit for '{pname}': {exc}") from None

    try:
        req_unit_canon = (
            normalize_unit(requested_unit)
            if requested_unit
            else basis_unit_canon
        )
    except UnknownUnitError as exc:
        raise PricingEngineError(f"Requested unit for '{pname}': {exc}") from None

    if inv_unit_canon is None:
        inv_unit_canon = basis_unit_canon

    # 4. Strict Wholesale Validation
    is_wholesale = str(pricing_status).strip().upper() == "WHOLESALE_ONLY" if pricing_status else False
    if is_wholesale:
        if req_unit_canon != inv_unit_canon:
            raise PricingEngineError(
                f"Product '{pname}' is wholesale-only and can only be sold in its configured container unit "
                f"('{get_unit(inv_unit_canon).label}'), not in '{get_unit(req_unit_canon).label}'."
            )
        if qty_d != qty_d.to_integral_value():
            raise InvalidQuantityError(
                f"Wholesale product '{pname}' cannot be sold in fractional quantities ({quantity}). "
                f"Only whole containers (1, 2, 3...) are permitted."
            )

    # 5. Convert requested quantity into the pricing basis unit
    try:
        normalized_qty_basis = convert_quantity(
            qty_d,
            req_unit_canon,
            basis_unit_canon,
            product_conversions=product_conversions,
        )
    except UnitError as exc:
        raise IncompatiblePricingUnitsError(
            f"Cannot calculate price for '{pname}': requested unit '{get_unit(req_unit_canon).label}' "
            f"is incompatible with pricing basis unit '{get_unit(basis_unit_canon).label}' ({exc})."
        ) from None

    # 6. Authoritative Line Calculation
    # Exact unrounded line total = (Q_basis / Q_basis_ref) * Price
    unrounded_line_total = (normalized_qty_basis * price_d) / basis_qty_d
    line_total = round_currency(unrounded_line_total)

    # Effective display unit price per 1 single unit of basis_unit
    effective_unit_price = round_price(price_d / basis_qty_d)

    # 7. Convert requested quantity into inventory unit for physical stock deduction
    try:
        stock_deduction_qty = convert_quantity(
            qty_d,
            req_unit_canon,
            inv_unit_canon,
            product_conversions=product_conversions,
        )
        # Validate that stock deduction adheres to the inventory unit's fractional capability
        stock_deduction_qty = validate_quantity_unit(stock_deduction_qty, inv_unit_canon)
    except UnitError as exc:
        raise IncompatiblePricingUnitsError(
            f"Cannot deduct stock for '{pname}': requested unit '{get_unit(req_unit_canon).label}' "
            f"is incompatible with physical inventory unit '{get_unit(inv_unit_canon).label}' ({exc})."
        ) from None

    # 8. Client Unit Price Assertion Check
    if client_unit_price is not None:
        client_price_d = validate_price(client_unit_price, name=f"Client unit price assertion for '{pname}'")
        # Client may assert either:
        # a) Effective rate per single basis unit (e.g. ₹0.30 per g in ₹30/100g)
        # b) Catalog reference price (e.g. ₹30.00)
        rate_per_single_basis = price_d / basis_qty_d
        diff_single = abs(client_price_d - rate_per_single_basis)
        diff_catalog = abs(client_price_d - price_d)
        tolerance = Decimal("0.01")

        if diff_single > tolerance and diff_catalog > tolerance:
            raise PriceAssertionError(
                f"Price assertion failed for '{pname}': client asserted ₹{client_price_d}, "
                f"but catalog price is ₹{price_d} per {basis_qty_d} {get_unit(basis_unit_canon).label} "
                f"(effective rate ₹{rate_per_single_basis:.3f}/{get_unit(basis_unit_canon).label})."
            )

    # 9. Statutory MRP Ceiling Enforcement
    line_mrp = None
    savings = None
    if mrp is not None and str(mrp).strip() != "":
        mrp_eval = evaluate_mrp_ceiling(
            selling_price=price_d,
            mrp=mrp,
            quantity=qty_d,
            requested_unit=req_unit_canon,
            price_basis_quantity=basis_qty_d,
            price_basis_unit=basis_unit_canon,
            mrp_basis_quantity=mrp_basis_quantity,
            mrp_basis_unit=mrp_basis_unit,
            product_conversions=product_conversions,
            product_name=pname,
        )
        line_mrp = mrp_eval.line_mrp_total
        savings = mrp_eval.savings_amount
        if mrp_eval.is_exceeded:
            raise MrpExceededError(
                f"Selling price ₹{line_total} for '{pname}' exceeds statutory Maximum Retail Price (MRP) ₹{mrp_eval.line_mrp_total}."
            )

    return LinePricingResult(
        line_total=line_total,
        unrounded_line_total=unrounded_line_total,
        effective_unit_price=effective_unit_price,
        normalized_quantity=normalized_qty_basis,
        pricing_basis_quantity=basis_qty_d,
        pricing_basis_unit=basis_unit_canon,
        requested_quantity=qty_d,
        requested_unit=req_unit_canon,
        stock_deduction_quantity=stock_deduction_qty,
        inventory_unit=inv_unit_canon,
        is_wholesale_only=is_wholesale,
        line_mrp_total=line_mrp,
        savings_amount=savings,
    )


# ----------------------------------------------------------------------------
# Cost & Statutory MRP Ceiling Evaluators
# ----------------------------------------------------------------------------


def calculate_purchase_cost(
    quantity: Any,
    requested_unit: Optional[str],
    purchase_price: Any,
    price_basis_quantity: Any = Decimal("1.0"),
    price_basis_unit: Optional[str] = None,
    product_conversions: Optional[Sequence[ProductUnitConversion]] = None,
    product_name: Optional[str] = None,
) -> PurchaseCostResult:
    """Calculate normalized procurement cost for an inventory line."""
    pname = product_name or "Product"
    cost_d = validate_price(purchase_price, name=f"Purchase price for '{pname}'")
    qty_d = validate_quantity(quantity, name=f"Quantity for '{pname}'")
    basis_qty_d = validate_quantity(price_basis_quantity, name=f"Price basis quantity for '{pname}'")

    basis_unit_canon = normalize_unit(price_basis_unit) if price_basis_unit else "pcs"
    req_unit_canon = normalize_unit(requested_unit) if requested_unit else basis_unit_canon

    norm_qty = convert_quantity(qty_d, req_unit_canon, basis_unit_canon, product_conversions=product_conversions)
    unrounded_cost = (norm_qty * cost_d) / basis_qty_d
    line_cost = round_currency(unrounded_cost)
    unit_cost = round_price(cost_d / basis_qty_d)

    return PurchaseCostResult(
        unit_cost=unit_cost,
        line_cost=line_cost,
        pricing_basis_quantity=basis_qty_d,
        pricing_basis_unit=basis_unit_canon,
        normalized_quantity=norm_qty,
    )


def evaluate_mrp_ceiling(
    selling_price: Any,
    mrp: Optional[Any],
    quantity: Any = Decimal("1.0"),
    requested_unit: Optional[str] = None,
    price_basis_quantity: Any = Decimal("1.0"),
    price_basis_unit: Optional[str] = None,
    mrp_basis_quantity: Optional[Any] = None,
    mrp_basis_unit: Optional[str] = None,
    product_conversions: Optional[Sequence[ProductUnitConversion]] = None,
    product_name: Optional[str] = None,
) -> MrpCeilingResult:
    """Evaluate whether retail selling price complies with statutory Maximum Retail Price (MRP).

    Normalizes selling price and MRP across package sizes, basis quantities, and unit conversions.
    Returns MrpCeilingResult. If MRP is None or zero, returns is_exceeded=False.
    Raises IncompatiblePricingUnitsError if selling price and MRP belong to different unit families.
    """
    pname = product_name or "Product"
    sp_d = validate_price(selling_price, name=f"Selling price for '{pname}'")

    if mrp is None or mrp == "":
        return MrpCeilingResult(
            mrp_per_basis=None,
            line_mrp_total=None,
            is_exceeded=False,
            savings_amount=None,
        )

    mrp_d = validate_price(mrp, name=f"MRP for '{pname}'")
    if mrp_d <= 0:
        return MrpCeilingResult(
            mrp_per_basis=None,
            line_mrp_total=None,
            is_exceeded=False,
            savings_amount=None,
        )

    qty_d = validate_quantity(quantity, name=f"Quantity for '{pname}'")
    sp_basis_qty_d = validate_quantity(price_basis_quantity, name=f"Price basis quantity for '{pname}'")
    mrp_basis_qty_d = validate_quantity(
        mrp_basis_quantity if mrp_basis_quantity is not None else price_basis_quantity,
        name=f"MRP basis quantity for '{pname}'"
    )

    sp_basis_canon = normalize_unit(price_basis_unit) if price_basis_unit else "pcs"
    mrp_basis_canon = normalize_unit(mrp_basis_unit) if mrp_basis_unit else sp_basis_canon
    req_unit_canon = normalize_unit(requested_unit) if requested_unit else sp_basis_canon

    # Check compatibility across units
    if not are_units_compatible(sp_basis_canon, mrp_basis_canon):
        raise IncompatiblePricingUnitsError(
            f"Cannot compare selling price in '{sp_basis_canon}' with statutory MRP in '{mrp_basis_canon}' for '{pname}'. Incompatible unit families."
        )

    if not are_units_compatible(req_unit_canon, sp_basis_canon):
        raise IncompatiblePricingUnitsError(
            f"Requested unit '{req_unit_canon}' cannot be converted to pricing unit '{sp_basis_canon}' for '{pname}'."
        )

    # Normalize quantity to both bases
    norm_qty_sp = convert_quantity(qty_d, req_unit_canon, sp_basis_canon, product_conversions=product_conversions)
    norm_qty_mrp = convert_quantity(qty_d, req_unit_canon, mrp_basis_canon, product_conversions=product_conversions)

    unrounded_sp_total = (norm_qty_sp * sp_d) / sp_basis_qty_d
    line_sp_total = round_currency(unrounded_sp_total)

    unrounded_mrp_total = (norm_qty_mrp * mrp_d) / mrp_basis_qty_d
    line_mrp_total = round_currency(unrounded_mrp_total)

    # Compare exact rates per base unit
    base_u = get_base_unit(sp_basis_canon)
    sp_base_qty = convert_quantity(sp_basis_qty_d, sp_basis_canon, base_u, product_conversions=product_conversions)
    rate_sp_base = sp_d / sp_base_qty

    mrp_base_qty = convert_quantity(mrp_basis_qty_d, mrp_basis_canon, base_u, product_conversions=product_conversions)
    rate_mrp_base = mrp_d / mrp_base_qty

    rate_diff = rate_sp_base - rate_mrp_base
    tolerance = Decimal("0.0001")
    is_exceeded = bool((rate_diff > tolerance) or (line_sp_total > line_mrp_total))
    savings = max(Decimal("0.00"), line_mrp_total - line_sp_total) if not is_exceeded else None

    return MrpCeilingResult(
        mrp_per_basis=mrp_d,
        line_mrp_total=line_mrp_total,
        is_exceeded=is_exceeded,
        savings_amount=savings,
        effective_sp_rate=rate_sp_base,
        effective_mrp_rate=rate_mrp_base,
    )
