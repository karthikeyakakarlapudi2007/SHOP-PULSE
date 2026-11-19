"""
Canonical unit registry (Phase 4, workstream 1).

Unit: every unit, alias, family, conversion, fraction rule, unknown unit and product-specific conversion.
Integration: OCR normaliser and product matching derive from the registry without changing behaviour;
GET /api/v1/units is read-only, authenticated and generated from the registry.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services import unit_registry as ur
from services.unit_registry import (
    ALIASES, FAMILIES, UNITS, IncompatibleUnitsError, InexactConversionError, InvalidProductConversionError,
    ProductUnitConversion, QuantityValidationError, UnknownUnitError, are_units_compatible, convert_quantity,
    get_base_unit, get_unit, get_unit_family, normalize_unit, try_normalize_unit, validate_quantity_unit,
)

D = Decimal

# The OCR alias table as it was before the registry (frozen copy of the former CANONICAL_UNITS literal)
LEGACY_OCR_ALIASES = {
    "pcs": "PCS", "pc": "PCS", "piece": "PCS", "pieces": "PCS", "nos": "NOS", "no": "NOS", "num": "NOS",
    "doz": "DOZ", "dozen": "DOZ", "dz": "DOZ", "set": "SET", "sets": "SET", "kg": "KG", "kgs": "KG",
    "kes": "KG", "kilo": "KG", "kilos": "KG", "kilogram": "KG", "kilograms": "KG", "g": "G", "gm": "G",
    "gms": "G", "gram": "G", "grams": "G", "qtl": "QTL", "quintal": "QTL", "ton": "TON", "tonne": "TON",
    "l": "L", "lt": "L", "ltr": "L", "ltrs": "L", "litre": "L", "litres": "L", "liter": "L", "liters": "L",
    "ml": "ML", "mls": "ML", "bag": "BAG", "bags": "BAG", "bor": "BOR", "bora": "BOR", "bori": "BOR",
    "boras": "BOR", "pkt": "PKT", "pkts": "PKT", "pack": "PKT", "packs": "PKT", "packet": "PKT",
    "packets": "PKT", "box": "BOX", "boxes": "BOX", "bx": "BOX", "pet": "PET", "pets": "PET", "btl": "PET",
    "btls": "PET", "bottle": "PET", "bottles": "PET", "tin": "TIN", "tins": "TIN", "can": "CAN", "cans": "CAN",
    "jar": "JAR", "jars": "JAR", "pouch": "POUCH", "pouches": "POUCH", "ctn": "CARTON", "carton": "CARTON",
    "cartons": "CARTON", "case": "CASE", "cases": "CASE",
}

# ------------------------------------------------------------------------------------- registry content


def test_required_units_and_families():
    expected = {"kg": ("mass", "g", 1000, True), "g": ("mass", "g", 1, True),
                "L": ("volume", "ml", 1000, True), "ml": ("volume", "ml", 1, True),
                "pcs": ("count", "pcs", 1, False), "dozen": ("count", "pcs", 12, False),
                "packet": ("packet", "packet", 1, False), "box": ("box", "box", 1, False),
                "bottle": ("bottle", "bottle", 1, False)}
    for uid, (family, base, factor, fraction) in expected.items():
        u = UNITS[uid]
        assert (u.family, u.base_unit, u.factor, u.allows_fraction) == (family, base, factor, fraction), uid


def test_every_unit_is_consistent():
    for u in UNITS.values():
        fam = FAMILIES[u.family]
        assert UNITS[fam.base_unit].family == fam.id and UNITS[fam.base_unit].factor == 1
        assert u.factor >= 1 and isinstance(u.factor, int)
        assert try_normalize_unit(u.id) == u.id  # the id itself is accepted
        # only kg, g, L, ml are fractional (approved D-1)
        assert u.allows_fraction == (u.id in {"kg", "g", "L", "ml"})


def test_each_package_type_is_its_own_family():
    packages = [f for f in FAMILIES.values() if f.kind == "package"]
    assert {"packet", "box", "bottle"} <= {f.id for f in packages}
    for f in packages:
        assert [u.id for u in UNITS.values() if u.family == f.id] == [f.id] and not f.auto_convertible


@pytest.mark.parametrize("raw,uid", [
    ("KG", "kg"), ("KGS", "kg"), ("kilogram", "kg"), ("Kilograms", "kg"), ("kgs.", "kg"),
    ("GM", "g"), ("GMS", "g"), ("gram", "g"), ("grams", "g"),
    ("LTR", "L"), ("litre", "L"), ("liter", "L"), ("litres", "L"), ("liters", "L"), ("l", "L"), ("L", "L"),
    ("ML", "ml"), ("millilitre", "ml"), ("milliliter", "ml"),
    ("PC", "pcs"), ("PCS", "pcs"), ("piece", "pcs"), ("pieces", "pcs"),
    ("DOZ", "dozen"), ("dozen", "dozen"),
    ("PKT", "packet"), ("packet", "packet"), ("packets", "packet"),
    ("BOX", "box"), ("boxes", "box"), ("BTL", "bottle"), ("bottle", "bottle"), ("bottles", "bottle"),
    ("  Kg ", "kg"), ("K.G.", "kg"),
])
def test_required_aliases(raw, uid):
    assert normalize_unit(raw) == uid


def test_every_alias_resolves_and_is_unique():
    for alias, uid in ALIASES.items():
        assert normalize_unit(alias) == uid and normalize_unit(alias.upper()) == uid
    assert len(ALIASES) == len(set(ALIASES))  # import would have failed on an ambiguous alias


@pytest.mark.parametrize("raw", ["xyz", "units", "bundle", "", None, "-", "kg2", "1"])
def test_unknown_units_are_errors_never_pcs(raw):
    assert try_normalize_unit(raw) is None
    with pytest.raises(UnknownUnitError, match="never assumed to be pcs"):
        normalize_unit(raw)


def test_family_and_base_helpers():
    assert get_unit_family("KGS").id == "mass" and get_base_unit("litre") == "ml" and get_base_unit("doz") == "pcs"
    assert get_unit("btl").label == "bottle"
    assert are_units_compatible("kg", "g") and are_units_compatible("dozen", "pcs") and are_units_compatible("L", "ml")
    assert not are_units_compatible("kg", "L") and not are_units_compatible("packet", "kg")
    assert not are_units_compatible("box", "pcs") and are_units_compatible("box", "boxes")


# ------------------------------------------------------------------------------------- conversion


@pytest.mark.parametrize("qty,src,dst,expected", [
    (2.5, "kg", "g", "2500"), (2500, "g", "kg", "2.5"), (0.75, "L", "ml", "750"), (1, "dozen", "pcs", "12"),
    ("0.125", "kg", "g", "125"), (125, "g", "kg", "0.125"), (30, "pcs", "dozen", "2.5"), (1, "qtl", "kg", "100"),
    (1.1, "kg", "g", "1100"),  # float input: no binary noise (1.1 * 1000 = 1100.0000000000002 as a float)
    (3, "packet", "packets", "3"),  # same package unit
])
def test_conversions_are_exact(qty, src, dst, expected):
    result = convert_quantity(qty, src, dst)
    assert result == D(expected) and str(result) == expected


@pytest.mark.parametrize("src,dst", [("kg", "L"), ("ml", "g"), ("packet", "kg"), ("box", "pcs"), ("bottle", "ml"),
                                     ("pcs", "kg"), ("packet", "box")])
def test_incompatible_conversions_fail(src, dst):
    with pytest.raises(IncompatibleUnitsError):
        convert_quantity(1, src, dst)


def test_package_error_names_product_configuration():
    with pytest.raises(IncompatibleUnitsError, match="product-specific conversion"):
        convert_quantity(1, "packet", "kg")


def test_inexact_conversion_is_refused_not_rounded():
    with pytest.raises(InexactConversionError):
        convert_quantity(10, "pcs", "dozen")  # 0.8333... dozen


def test_unknown_unit_in_conversion():
    with pytest.raises(UnknownUnitError):
        convert_quantity(1, "kg", "xyz")


# ------------------------------------------------------------------------------------- quantity validation


@pytest.mark.parametrize("qty,unit,expected", [
    (2.5, "kg", "2.5"), ("0.75", "L", "0.75"), (0.125, "kg", "0.125"), (12, "pcs", "12"), (2, "dozen", "2"),
    (3, "box", "3"), (3.0, "packet", "3"),
])
def test_valid_quantities(qty, unit, expected):
    assert str(validate_quantity_unit(qty, unit)) == expected


@pytest.mark.parametrize("qty,unit,message", [
    (2.5, "pcs", "whole numbers"), (0.5, "dozen", "whole numbers"), (1.5, "packet", "whole numbers"),
    (1.5, "box", "whole numbers"), (2.5, "bottle", "whole numbers"), (1.2345, "kg", "3 decimal"),
    (0, "kg", "greater than 0"), (-1, "g", "greater than 0"), ("abc", "kg", "not a number"),
    (float("nan"), "kg", "not a finite"), (True, "kg", "boolean"),
])
def test_invalid_quantities(qty, unit, message):
    with pytest.raises(QuantityValidationError, match=message):
        validate_quantity_unit(qty, unit)


def test_zero_allowed_when_requested():
    assert validate_quantity_unit(0, "kg", allow_zero=True) == 0


# ------------------------------------------------------------------------------------- product-specific conversions


def test_product_conversion_applies_only_when_supplied():
    box24 = ProductUnitConversion.create("box", "pcs", 24, product_id="p-1")
    assert convert_quantity(2, "box", "pcs", [box24]) == 48
    assert convert_quantity(2, "box", "dozen", [box24]) == 4  # box -> pcs -> dozen
    assert convert_quantity(48, "pcs", "box", [box24]) == 2  # reverse direction
    with pytest.raises(IncompatibleUnitsError):
        convert_quantity(2, "box", "pcs")  # no global assumption
    bag = ProductUnitConversion.create("bag", "kg", 25)
    assert convert_quantity(3, "bag", "g", [bag]) == 75000
    pkt = ProductUnitConversion.create("packet", "kg", "0.5")
    assert convert_quantity(4, "packet", "kg", [pkt]) == 2


@pytest.mark.parametrize("src,dst,factor,message", [
    ("kg", "g", 1000, "package unit"), ("box", "box", 1, "needs no"), ("box", "pcs", 2.5, "whole numbers"),
    ("box", "pcs", 0, "greater than 0"), ("packet", "kg", "0.0001", "decimal"),
])
def test_invalid_product_conversions(src, dst, factor, message):
    with pytest.raises(InvalidProductConversionError, match=message):
        ProductUnitConversion.create(src, dst, factor)


def test_conflicting_product_conversions_are_refused():
    a, b = ProductUnitConversion.create("box", "pcs", 24), ProductUnitConversion.create("box", "pcs", 12)
    with pytest.raises(InvalidProductConversionError, match="Conflicting"):
        convert_quantity(1, "box", "pcs", [a, b])


# ------------------------------------------------------------------------------------- integration: OCR and matching


def test_ocr_normaliser_keeps_every_former_alias_and_code():
    from services.grocery_ocr.extraction.unit_normalizer import CANONICAL_UNITS, UnitNormalizer

    for alias, code in LEGACY_OCR_ALIASES.items():
        assert CANONICAL_UNITS[alias] == code, alias
        assert UnitNormalizer().normalize(alias.upper()).normalized_unit == code
    added = set(CANONICAL_UNITS) - set(LEGACY_OCR_ALIASES)
    assert added == {"gr", "quintals", "tons", "tonnes", "millilitre", "millilitres", "milliliter", "milliliters", "dozens"}


@pytest.mark.parametrize("raw", ["XYZ", "Bundle", "units"])
def test_ocr_unknown_unit_is_kept_and_flagged_not_pcs(raw):
    from services.grocery_ocr.extraction.unit_normalizer import UnitNormalizer

    res = UnitNormalizer().normalize(raw)
    assert res.is_recognized is False and res.normalized_unit == raw.upper() and res.normalized_unit != "PCS"


@pytest.mark.parametrize("name,expected", [
    ("Aashirvaad Atta 5kg", "aashirvaad atta 5000g"), ("Tata Salt 1 KG", "tata salt 1000g"),
    ("Amul Milk 500ml", "amul milk 500ml"), ("Fortune Oil 1L", "fortune oil 1000ml"), ("Tea 250 gr", "tea 250g"),
    ("Rice 25 kilos", "rice 25000g"),  # "kilos" now resolved through the registry (was left as text)
])
def test_product_matching_uses_registry_factors(name, expected):
    from services.product_matching import extract_pack_size, normalize_name

    assert normalize_name(name) == expected
    assert extract_pack_size(name)[0] in ("g", "ml")


# ------------------------------------------------------------------------------------- integration: API

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
_Session = sessionmaker(bind=_engine)


@pytest.fixture()
def client():
    import db.models  # noqa: F401
    from api.deps import get_db
    from db.session import Base
    from main import app

    Base.metadata.create_all(bind=_engine)

    def _db():
        s = _Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=_engine)


def _token(c):
    email = f"units{uuid.uuid4().hex[:8]}@example.com"
    c.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    return c.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]


def test_units_endpoint_requires_authentication(client):
    assert client.get("/api/v1/units").status_code == 401


def test_units_endpoint_returns_the_registry(client):
    r = client.get("/api/v1/units", headers={"Authorization": f"Bearer {_token(client)}"})
    assert r.status_code == 200
    body = r.json()
    assert body == ur.registry_payload()  # generated from the registry, not a second copy
    kg = next(u for u in body["units"] if u["id"] == "kg")
    assert kg == {"id": "kg", "label": "kg", "family": "mass", "kind": "measure", "base_unit": "g",
                  "factor_to_base": 1000, "allows_fraction": True, "convertible": True,
                  "compatible_units": ["kg", "g", "qtl", "ton"],
                  "aliases": ["kes", "kg", "kgs", "kilo", "kilogram", "kilograms", "kilos"]}
    box = next(u for u in body["units"] if u["id"] == "box")
    assert box["convertible"] is False and box["compatible_units"] == ["box"] and box["allows_fraction"] is False
    assert {f["id"] for f in body["families"]} >= {"mass", "volume", "count", "packet", "box", "bottle"}


def test_units_endpoint_is_read_only(client):
    h = {"Authorization": f"Bearer {_token(client)}"}
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/units", headers=h).status_code == 405


def test_frontend_registry_fixture_matches_the_registry():
    """src/tests/fixtures/unit_registry.json (used by the frontend tests) must equal the live registry.
    Regenerate it with: python -c "import json; from services.unit_registry import registry_payload;
    open('../src/tests/fixtures/unit_registry.json','w').write(json.dumps(registry_payload(), indent=1) + '\\n')"
    """
    import json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "src" / "tests" / "fixtures" / "unit_registry.json"
    assert json.loads(fixture.read_text()) == ur.registry_payload()


# ------------------------------------------------------------------------------------- product matching with the registry
# Names are generated from made-up brand words, product categories and sizes (no individual products).

_BRANDS = ["Northfield", "Riverstone", "Hilltop", "Lakeview"]
_ITEMS = ["Basmati Rice", "Wheat Flour", "Toor Dal", "Sunflower Oil"]
_SAME_MASS = ["5 kg", "5 kgs", "5 kilo", "5 kilos", "5 kilogram", "5000 g", "5000 gm", "5000 grams"]


@pytest.mark.parametrize("item", _ITEMS)
def test_same_pack_size_in_any_spelling_matches(item):
    from services.product_matching import name_similarity

    base = f"{_BRANDS[0]} {item}"
    for a in _SAME_MASS:
        for b in _SAME_MASS:
            assert name_similarity(f"{base} {a}", f"{base} {b}") == 1.0, (a, b)


@pytest.mark.parametrize("a,b", [
    ("25 kilos", "25 kg"), ("2.5 kilos", "2500 g"), ("1 litre", "1000 ml"), ("0.5 L", "500 ml"),
])
def test_equivalent_sizes_match(a, b):
    from services.product_matching import name_similarity

    for item in _ITEMS:
        assert name_similarity(f"{item} {a}", f"{item} {b}") == 1.0


@pytest.mark.parametrize("a,b", [
    ("25 kg", "25 g"), ("5 kilos", "10 kilos"), ("2.5 kilos", "25 kilos"), ("25 kilos", "2500 g"),
    ("1 L", "1 kg"), ("1 litre", "500 ml"), ("5 kg", "5 L"),
])
def test_different_sizes_never_match(a, b):
    from services.product_matching import best_name_match, name_similarity

    for item in _ITEMS:
        assert name_similarity(f"{item} {a}", f"{item} {b}") == 0.0
        assert best_name_match(f"{item} {a}", [f"{item} {b}"], lambda x: x).candidate is None


@pytest.mark.parametrize("size", ["5 kg", "5 kilos", "5000 g"])
def test_distinct_brands_with_the_same_weight_do_not_match(size):
    from services.product_matching import best_name_match

    for item in _ITEMS:
        query = f"{_BRANDS[0]} {item} 5 kg"
        others = [f"{b} {item} {size}" for b in _BRANDS[1:]]
        assert best_name_match(query, others, lambda x: x).candidate is None, (item, size)


def test_distinct_items_of_one_brand_with_the_same_weight_do_not_match():
    from services.product_matching import best_name_match

    for i, item in enumerate(_ITEMS):
        others = [f"{_BRANDS[0]} {o} 5 kilos" for j, o in enumerate(_ITEMS) if j != i]
        assert best_name_match(f"{_BRANDS[0]} {item} 5 kg", others, lambda x: x).candidate is None


def test_count_or_package_text_is_not_a_pack_size():
    from services.product_matching import best_name_match, extract_pack_size

    for item in _ITEMS:
        assert extract_pack_size(f"{item} 25 packets") is None
        assert best_name_match(f"{item} 25 kg", [f"{item} 25 packets"], lambda x: x).candidate is None


def test_the_right_size_is_chosen_among_sizes():
    from services.product_matching import best_name_match

    for item in _ITEMS:
        name = f"{_BRANDS[1]} {item}"
        catalog = [f"{name} 1 kg", f"{name} 5000 g", f"{name} 10 kg", f"{name} 2.5 kilos"]
        assert best_name_match(f"{name} 5 kilos", catalog, lambda x: x).candidate == f"{name} 5000 g"
        assert best_name_match(f"{name} 2500 g", catalog, lambda x: x).candidate == f"{name} 2.5 kilos"
