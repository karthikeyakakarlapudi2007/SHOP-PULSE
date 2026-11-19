"""
Canonical unit registry (Phase 4, workstream 1).

The single source of truth for units in ShopPulse. It extends the former OCR unit table
(``services/grocery_ocr/extraction/unit_normalizer.CANONICAL_UNITS``): every one of its aliases and
codes is kept here, and the OCR normaliser and product-name matching now derive their tables from this
module. The read-only API ``GET /api/v1/units`` serialises it for the frontend.

Rules (approved Phase 4 decisions D-1, D-4):
  * Units convert only within their family: mass (base g), volume (base ml), count (base pcs).
  * Each package type (packet, box, bottle, ...) is its own family and never converts automatically to
    mass, volume or count. Only an explicit, product-specific conversion may do that.
  * kg, g, L, ml allow fractional quantities (up to 3 decimals). Every other unit is whole-number.
  * An unknown unit is an error (``UnknownUnitError``) - never silently treated as pcs.
  * Arithmetic is Decimal and exact; an inexact conversion is refused instead of rounded.

This module only provides metadata, normalisation, validation and conversion. Applying it to stock,
sales or purchases is done in later workstreams.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, Inexact, InvalidOperation, localcontext
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

QuantityInput = Union[int, str, Decimal, float]

#: Maximum decimal places for a fractional quantity (matches the 3-dp quantity precision of Phase 3A).
MAX_FRACTION_DIGITS = 3


# ---------------------------------------------------------------------------- errors


class UnitError(ValueError):
    """Base class for unit errors (subclass of ValueError for existing ``except ValueError`` handlers)."""


class UnknownUnitError(UnitError):
    def __init__(self, raw: object):
        self.raw = raw
        super().__init__(
            f"Unknown unit {raw!r}: it is not in the unit registry. Correct the unit or review the line "
            "(it is never assumed to be pcs).")


class IncompatibleUnitsError(UnitError):
    pass


class InexactConversionError(UnitError):
    pass


class InvalidProductConversionError(UnitError):
    pass


class QuantityValidationError(UnitError):
    pass


# ---------------------------------------------------------------------------- definitions


@dataclass(frozen=True)
class UnitFamily:
    id: str
    label: str
    kind: str  # "measure" | "count" | "package"
    base_unit: str

    @property
    def auto_convertible(self) -> bool:
        """Units of this family convert to each other automatically (mass, volume, count)."""
        return self.kind in ("measure", "count")


@dataclass(frozen=True)
class UnitDefinition:
    id: str
    label: str
    family: str
    factor: int  # quantity of the family's base unit in one of this unit (all factors are whole numbers)
    allows_fraction: bool
    ocr_code: str  # code produced by the OCR normaliser (kept for backward compatibility)
    aliases: Tuple[str, ...] = ()

    @property
    def base_unit(self) -> str:
        return FAMILIES[self.family].base_unit


_FAMILY_LIST: Tuple[UnitFamily, ...] = (
    UnitFamily("mass", "Mass", "measure", "g"),
    UnitFamily("volume", "Volume", "measure", "ml"),
    UnitFamily("count", "Count", "count", "pcs"),
    # Package units: each its own family, base = itself (no automatic conversion to anything else)
    *(UnitFamily(pid, label, "package", pid) for pid, label in (
        ("packet", "Packet"), ("box", "Box"), ("bottle", "Bottle"), ("bag", "Bag"), ("bora", "Bora"),
        ("tin", "Tin"), ("can", "Can"), ("jar", "Jar"), ("pouch", "Pouch"), ("carton", "Carton"),
        ("case", "Case"), ("set", "Set"),
    )),
)

# Aliases are matched after normalisation (lower case, punctuation and spaces removed). The former OCR
# aliases are all kept; additions are the product-matching aliases ("gr") and the approved spellings
# (millilitre, milliliter, btl, dozens, ...).
_UNIT_LIST: Tuple[UnitDefinition, ...] = (
    # Mass (base g)
    UnitDefinition("kg", "kg", "mass", 1000, True, "KG",
                   ("kg", "kgs", "kes", "kilo", "kilos", "kilogram", "kilograms")),
    UnitDefinition("g", "g", "mass", 1, True, "G", ("g", "gm", "gms", "gr", "gram", "grams")),
    UnitDefinition("qtl", "quintal", "mass", 100_000, False, "QTL", ("qtl", "quintal", "quintals")),
    UnitDefinition("ton", "tonne", "mass", 1_000_000, False, "TON", ("ton", "tons", "tonne", "tonnes")),
    # Volume (base ml)
    UnitDefinition("L", "L", "volume", 1000, True, "L",
                   ("l", "lt", "ltr", "ltrs", "litre", "litres", "liter", "liters")),
    UnitDefinition("ml", "ml", "volume", 1, True, "ML",
                   ("ml", "mls", "millilitre", "millilitres", "milliliter", "milliliters")),
    # Count (base pcs)
    UnitDefinition("pcs", "pcs", "count", 1, False, "PCS", ("pcs", "pc", "piece", "pieces")),
    UnitDefinition("nos", "nos", "count", 1, False, "NOS", ("nos", "no", "num")),
    UnitDefinition("dozen", "dozen", "count", 12, False, "DOZ", ("doz", "dz", "dozen", "dozens")),
    # Packages (each its own family)
    UnitDefinition("packet", "packet", "packet", 1, False, "PKT",
                   ("pkt", "pkts", "pack", "packs", "packet", "packets")),
    UnitDefinition("box", "box", "box", 1, False, "BOX", ("box", "boxes", "bx")),
    UnitDefinition("bottle", "bottle", "bottle", 1, False, "PET",
                   ("bottle", "bottles", "btl", "btls", "pet", "pets")),
    UnitDefinition("bag", "bag", "bag", 1, False, "BAG", ("bag", "bags")),
    UnitDefinition("bora", "bora", "bora", 1, False, "BOR", ("bor", "bora", "bori", "boras")),
    UnitDefinition("tin", "tin", "tin", 1, False, "TIN", ("tin", "tins")),
    UnitDefinition("can", "can", "can", 1, False, "CAN", ("can", "cans")),
    UnitDefinition("jar", "jar", "jar", 1, False, "JAR", ("jar", "jars")),
    UnitDefinition("pouch", "pouch", "pouch", 1, False, "POUCH", ("pouch", "pouches")),
    UnitDefinition("carton", "carton", "carton", 1, False, "CARTON", ("ctn", "carton", "cartons")),
    UnitDefinition("case", "case", "case", 1, False, "CASE", ("case", "cases")),
    UnitDefinition("set", "set", "set", 1, False, "SET", ("set", "sets")),
)

FAMILIES: Dict[str, UnitFamily] = {f.id: f for f in _FAMILY_LIST}
UNITS: Dict[str, UnitDefinition] = {u.id: u for u in _UNIT_LIST}


def clean_unit_text(raw: object) -> str:
    """Normalise unit text for alias lookup: drop punctuation / spaces, lower case ("Kgs." -> "kgs")."""
    return re.sub(r"[^\w]", "", str(raw)).lower() if raw is not None else ""


def _build_alias_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for unit in _UNIT_LIST:
        if unit.family not in FAMILIES:
            raise RuntimeError(f"unit {unit.id}: unknown family {unit.family}")
        for alias in {clean_unit_text(unit.id), *unit.aliases}:
            if alias != clean_unit_text(alias):
                raise RuntimeError(f"alias {alias!r} of {unit.id} is not in normalised form")
            if alias in index and index[alias] != unit.id:  # an alias may mean only one unit
                raise RuntimeError(f"alias {alias!r} is ambiguous: {index[alias]} and {unit.id}")
            index[alias] = unit.id
    for family in _FAMILY_LIST:
        base = UNITS.get(family.base_unit)
        if base is None or base.family != family.id or base.factor != 1:
            raise RuntimeError(f"family {family.id}: base unit {family.base_unit} must be a factor-1 member")
    return index


ALIASES: Dict[str, str] = _build_alias_index()


# ---------------------------------------------------------------------------- lookup


def try_normalize_unit(raw: object) -> Optional[str]:
    """Canonical unit id for ``raw`` ("KGS" -> "kg"), or None when it is not a registered unit."""
    return ALIASES.get(clean_unit_text(raw))


def normalize_unit(raw: object) -> str:
    """Canonical unit id for ``raw``; raises UnknownUnitError for an unknown or empty unit."""
    unit_id = try_normalize_unit(raw)
    if unit_id is None:
        raise UnknownUnitError(raw)
    return unit_id


def get_unit(raw: object) -> UnitDefinition:
    """Registered unit for a name / alias (or an already resolved UnitDefinition)."""
    if isinstance(raw, UnitDefinition):
        return raw
    return UNITS[normalize_unit(raw)]


def get_unit_family(raw: object) -> UnitFamily:
    return FAMILIES[get_unit(raw).family]


def get_base_unit(raw: object) -> str:
    return get_unit(raw).base_unit


def are_units_compatible(a: object, b: object) -> bool:
    """True when ``a`` converts to ``b`` without product-specific configuration (same family)."""
    return get_unit(a).family == get_unit(b).family


def compatible_units(raw: object) -> List[str]:
    family = get_unit(raw).family
    return [u.id for u in _UNIT_LIST if u.family == family]


# ---------------------------------------------------------------------------- quantities


def to_decimal(quantity: QuantityInput) -> Decimal:
    """Exact Decimal for a quantity. Floats use their shortest repr (0.1 -> Decimal('0.1'))."""
    if isinstance(quantity, bool):
        raise QuantityValidationError("A quantity must be a number, not a boolean.")
    try:
        value = Decimal(str(quantity)) if isinstance(quantity, float) else Decimal(quantity)
    except (InvalidOperation, TypeError, ValueError):
        raise QuantityValidationError(f"Quantity {quantity!r} is not a number.") from None
    if not value.is_finite():
        raise QuantityValidationError(f"Quantity {quantity!r} is not a finite number.")
    return value


def _tidy(value: Decimal) -> Decimal:
    """2500.0 -> 2500, 2.50 -> 2.5 (no exponent notation)."""
    if value == value.to_integral_value():
        return value.quantize(Decimal(1))
    return value.normalize()


def validate_quantity_unit(quantity: QuantityInput, unit: object, *, allow_zero: bool = False) -> Decimal:
    """Validate ``quantity`` for ``unit`` and return it as an exact Decimal.

    Fractional units (kg, g, L, ml) accept up to 3 decimals; every other unit needs a whole number.
    Raises QuantityValidationError (bad quantity) or UnknownUnitError (bad unit).
    """
    definition = get_unit(unit)
    value = to_decimal(quantity)
    if value < 0 or (value == 0 and not allow_zero):
        raise QuantityValidationError(
            f"Quantity must be {'0 or more' if allow_zero else 'greater than 0'}, got {quantity} {definition.label}.")
    places = -value.normalize().as_tuple().exponent if value != 0 else 0
    if not definition.allows_fraction and places > 0:
        raise QuantityValidationError(
            f"{definition.label} is counted in whole numbers; {quantity} {definition.label} is not allowed.")
    if places > MAX_FRACTION_DIGITS:
        raise QuantityValidationError(
            f"Quantity {quantity} {definition.label} has more than {MAX_FRACTION_DIGITS} decimal places.")
    return _tidy(value)


# ---------------------------------------------------------------------------- conversion


@dataclass(frozen=True)
class ProductUnitConversion:
    """An explicitly configured conversion for ONE product, e.g. 1 box = 24 pcs.

    Not persisted in this workstream (persisting needs an approved schema change); callers pass the
    conversions of the product they are working on. ``from_unit`` must be a package unit and ``to_unit``
    must belong to another family.
    """

    from_unit: str
    to_unit: str
    factor: Decimal
    product_id: Optional[str] = None

    @classmethod
    def create(cls, from_unit: object, to_unit: object, factor: QuantityInput,
               product_id: Optional[str] = None) -> "ProductUnitConversion":
        src, dst = get_unit(from_unit), get_unit(to_unit)
        if FAMILIES[src.family].kind != "package":
            raise InvalidProductConversionError(
                f"Product-specific conversions start from a package unit (packet, box, bottle, ...); "
                f"{src.label} already converts through its family.")
        if src.family == dst.family:
            raise InvalidProductConversionError(f"{src.label} -> {dst.label} needs no product-specific conversion.")
        try:
            value = validate_quantity_unit(factor, dst)
        except QuantityValidationError as exc:
            raise InvalidProductConversionError(f"Invalid conversion 1 {src.label} = {factor} {dst.label}: {exc}") from None
        return cls(src.id, dst.id, value, product_id)


def _scale(quantity: Decimal, numerator: Decimal, denominator: Decimal, what: str) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 34
        ctx.traps[Inexact] = True
        try:
            return quantity * numerator / denominator
        except Inexact:
            raise InexactConversionError(f"{what} has no exact decimal result.") from None


def _within_family(value: Decimal, src: UnitDefinition, dst: UnitDefinition) -> Decimal:
    return _scale(value, Decimal(src.factor), Decimal(dst.factor), f"Converting {value} {src.label} to {dst.label}")


def convert_quantity(quantity: QuantityInput, from_unit: object, to_unit: object,
                     product_conversions: Optional[Sequence[ProductUnitConversion]] = None) -> Decimal:
    """Convert exactly between units.

    Within a family (kg<->g, L<->ml, dozen<->pcs) the registry factors are used. Across families
    (e.g. box -> pcs) only an explicitly supplied ``ProductUnitConversion`` of that product is used.
    Raises IncompatibleUnitsError, InexactConversionError or UnknownUnitError; never rounds.
    """
    src, dst = get_unit(from_unit), get_unit(to_unit)
    value = to_decimal(quantity)
    if src.family == dst.family:
        return _tidy(_within_family(value, src, dst))

    routes: List[Decimal] = []
    for conv in product_conversions or ():
        mid = UNITS[conv.to_unit]
        if conv.from_unit == src.id and mid.family == dst.family:  # e.g. 2 box -> 48 pcs -> 4 dozen
            routes.append(_within_family(_scale(value, conv.factor, Decimal(1), "Product conversion"), mid, dst))
        elif conv.from_unit == dst.id and mid.family == src.family:  # e.g. 48 pcs -> 2 box
            routes.append(_scale(_within_family(value, src, mid), Decimal(1), conv.factor, "Product conversion"))
    if len(set(routes)) > 1:
        raise InvalidProductConversionError(
            f"Conflicting product conversions between {src.label} and {dst.label}.")
    if routes:
        return _tidy(routes[0])

    if FAMILIES[src.family].kind == "package" or FAMILIES[dst.family].kind == "package":
        raise IncompatibleUnitsError(
            f"{src.label} cannot be converted to {dst.label} without a product-specific conversion "
            "(package sizes are never assumed).")
    raise IncompatibleUnitsError(
        f"{src.label} ({FAMILIES[src.family].label.lower()}) cannot be converted to "
        f"{dst.label} ({FAMILIES[dst.family].label.lower()}).")


# ---------------------------------------------------------------------------- derived tables


def ocr_alias_map() -> Dict[str, str]:
    """alias -> OCR code (e.g. "kgs" -> "KG", "bottle" -> "PET"), for the OCR unit normaliser."""
    return {alias: UNITS[unit_id].ocr_code for alias, unit_id in ALIASES.items()}


def units_in_families(kinds: Iterable[str]) -> List[UnitDefinition]:
    kinds = set(kinds)
    return [u for u in _UNIT_LIST if FAMILIES[u.family].kind in kinds]


def registry_payload() -> dict:
    """The registry as plain data (the body of GET /api/v1/units)."""
    return {
        "version": 1,
        "max_fraction_digits": MAX_FRACTION_DIGITS,
        "families": [
            {"id": f.id, "label": f.label, "kind": f.kind, "base_unit": f.base_unit,
             "auto_convertible": f.auto_convertible,
             "units": [u.id for u in _UNIT_LIST if u.family == f.id]}
            for f in _FAMILY_LIST
        ],
        "units": [
            {"id": u.id, "label": u.label, "family": u.family, "kind": FAMILIES[u.family].kind,
             "base_unit": u.base_unit, "factor_to_base": u.factor, "allows_fraction": u.allows_fraction,
             "convertible": FAMILIES[u.family].auto_convertible,
             "compatible_units": compatible_units(u.id),
             "aliases": sorted({a for a, uid in ALIASES.items() if uid == u.id})}
            for u in _UNIT_LIST
        ],
    }
