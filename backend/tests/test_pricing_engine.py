"""
Dedicated tests for Universal Decimal Pricing Engine (Stage 1).

Tests pure Decimal calculation logic, unit normalization, rounding rules,
error handling, and safety gating in complete isolation (no DB connection).
"""

from decimal import Decimal
import pytest

from services.pricing_engine import (
    IncompatiblePricingUnitsError,
    InvalidPriceError,
    InvalidPricingBasisError,
    InvalidQuantityError,
    LinePricingResult,
    MrpCeilingResult,
    PriceAssertionError,
    PricingEngineError,
    PricingStatusError,
    PurchaseCostResult,
    calculate_line_price,
    calculate_purchase_cost,
    evaluate_mrp_ceiling,
    to_exact_decimal,
    validate_price,
    validate_quantity,
)
from services.unit_registry import (
    ProductUnitConversion,
    UnknownUnitError,
)

D = Decimal


# ============================================================================
# Section A: Weight Calculations
# ============================================================================


def test_weight_half_kg():
    """₹48/kg x 500g = ₹24.00"""
    res = calculate_line_price(
        quantity=500,
        requested_unit="g",
        selling_price=48,
        price_basis_quantity=1,
        price_basis_unit="kg",
        inventory_unit="kg",
        product_name="Sugar",
    )
    assert res.line_total == D("24.00")
    assert res.unrounded_line_total == D("24.00")
    assert res.effective_unit_price == D("48.000")
    assert res.normalized_quantity == D("0.5")
    assert res.stock_deduction_quantity == D("0.5")
    assert res.inventory_unit == "kg"


def test_weight_quarter_kg():
    """₹48/kg x 250g = ₹12.00"""
    res = calculate_line_price(
        quantity=250,
        requested_unit="g",
        selling_price=48,
        price_basis_quantity=1,
        price_basis_unit="kg",
        inventory_unit="kg",
        product_name="Sugar",
    )
    assert res.line_total == D("12.00")
    assert res.normalized_quantity == D("0.25")
    assert res.stock_deduction_quantity == D("0.25")


def test_weight_one_kg():
    """₹48/kg x 1kg = ₹48.00"""
    res = calculate_line_price(
        quantity=1,
        requested_unit="kg",
        selling_price=48,
        price_basis_quantity=1,
        price_basis_unit="kg",
        inventory_unit="kg",
        product_name="Sugar",
    )
    assert res.line_total == D("48.00")
    assert res.normalized_quantity == D("1")
    assert res.stock_deduction_quantity == D("1")


def test_weight_fractional_kg():
    """₹48/kg x 1.5kg = ₹72.00"""
    res = calculate_line_price(
        quantity="1.5",
        requested_unit="kg",
        selling_price="48.00",
        price_basis_quantity=1,
        price_basis_unit="kg",
        inventory_unit="kg",
        product_name="Sugar",
    )
    assert res.line_total == D("72.00")
    assert res.normalized_quantity == D("1.5")
    assert res.stock_deduction_quantity == D("1.5")


# ============================================================================
# Section B: Volume Calculations
# ============================================================================


def test_volume_750ml():
    """₹120/L x 750ml = ₹90.00"""
    res = calculate_line_price(
        quantity=750,
        requested_unit="ml",
        selling_price=120,
        price_basis_quantity=1,
        price_basis_unit="L",
        inventory_unit="L",
        product_name="Sunflower Oil",
    )
    assert res.line_total == D("90.00")
    assert res.normalized_quantity == D("0.75")
    assert res.stock_deduction_quantity == D("0.75")


def test_volume_500ml():
    """₹120/L x 500ml = ₹60.00"""
    res = calculate_line_price(
        quantity=500,
        requested_unit="ml",
        selling_price=120,
        price_basis_quantity=1,
        price_basis_unit="L",
        inventory_unit="L",
        product_name="Sunflower Oil",
    )
    assert res.line_total == D("60.00")
    assert res.normalized_quantity == D("0.5")
    assert res.stock_deduction_quantity == D("0.5")


# ============================================================================
# Section C: Discrete Products
# ============================================================================


def test_discrete_packets():
    """₹20/packet x 2 packets = ₹40.00"""
    res = calculate_line_price(
        quantity=2,
        requested_unit="packet",
        selling_price=20,
        price_basis_quantity=1,
        price_basis_unit="packet",
        inventory_unit="packet",
        product_name="Salt Packet",
    )
    assert res.line_total == D("40.00")
    assert res.normalized_quantity == D("2")
    assert res.stock_deduction_quantity == D("2")


def test_discrete_pieces():
    """₹35/pcs x 3 pcs = ₹105.00"""
    res = calculate_line_price(
        quantity=3,
        requested_unit="pcs",
        selling_price=35,
        price_basis_quantity=1,
        price_basis_unit="pcs",
        inventory_unit="pcs",
        product_name="Soap Bar",
    )
    assert res.line_total == D("105.00")
    assert res.normalized_quantity == D("3")
    assert res.stock_deduction_quantity == D("3")


def test_discrete_aliases():
    """Aliases 'pkt', 'pkts', 'pack' resolve to canonical 'packet'."""
    res1 = calculate_line_price(quantity=2, requested_unit="pkt", selling_price=10, price_basis_unit="packet")
    res2 = calculate_line_price(quantity=2, requested_unit="pkts", selling_price=10, price_basis_unit="pack")
    assert res1.line_total == D("20.00")
    assert res2.line_total == D("20.00")
    assert res1.pricing_basis_unit == "packet"
    assert res2.pricing_basis_unit == "packet"


# ============================================================================
# Section D: Different Pricing Basis (Sub-unit & Multi-unit)
# ============================================================================


def test_sub_unit_basis_spice():
    """₹50 per 100g x 250g = ₹125.00"""
    res = calculate_line_price(
        quantity=250,
        requested_unit="g",
        selling_price=50,
        price_basis_quantity=100,
        price_basis_unit="g",
        inventory_unit="kg",
        product_name="Cardamom",
    )
    assert res.line_total == D("125.00")
    assert res.effective_unit_price == D("0.500")  # ₹0.50 per gram
    assert res.normalized_quantity == D("250")
    assert res.stock_deduction_quantity == D("0.25")  # 0.25 kg deducted


def test_multi_unit_basis_flour():
    """₹200 per 5kg x 1kg = ₹40.00"""
    res = calculate_line_price(
        quantity=1,
        requested_unit="kg",
        selling_price=200,
        price_basis_quantity=5,
        price_basis_unit="kg",
        inventory_unit="kg",
        product_name="Atta",
    )
    assert res.line_total == D("40.00")
    assert res.effective_unit_price == D("40.000")  # ₹40 per kg
    assert res.normalized_quantity == D("1")
    assert res.stock_deduction_quantity == D("1")


def test_dozen_to_piece():
    """₹480 per 12 pcs x 1 pc = ₹40.00, 6 pcs = ₹240.00"""
    res_1 = calculate_line_price(
        quantity=1,
        requested_unit="pcs",
        selling_price=480,
        price_basis_quantity=12,
        price_basis_unit="pcs",
        inventory_unit="pcs",
    )
    assert res_1.line_total == D("40.00")
    assert res_1.stock_deduction_quantity == D("1")

    res_6 = calculate_line_price(
        quantity=6,
        requested_unit="pcs",
        selling_price=480,
        price_basis_quantity=12,
        price_basis_unit="pcs",
        inventory_unit="pcs",
    )
    assert res_6.line_total == D("240.00")
    assert res_6.stock_deduction_quantity == D("6")


# ============================================================================
# Section E: Rounding Rules (ROUND_HALF_UP)
# ============================================================================


@pytest.mark.parametrize(
    "qty,price,expected_total",
    [
        (1, "1.005", "1.01"),    # 1.005 -> 1.01
        (1, "2.675", "2.68"),    # 2.675 -> 2.68
        (1, "0.125", "0.13"),    # 0.125 -> 0.13
        (1, "10.245", "10.25"),  # 10.245 -> 10.25
        (1, "33.375", "33.38"),  # 33.375 -> 33.38
        (1, "100.005", "100.01"),# 100.005 -> 100.01
        (3, "33.3333333333", "100.00"), # 3 x 33.3333333333 = 100.00
    ],
)
def test_currency_half_up_paise_rounding(qty, price, expected_total):
    res = calculate_line_price(
        quantity=qty,
        requested_unit="pcs",
        selling_price=price,
        price_basis_quantity=1,
        price_basis_unit="pcs",
    )
    assert res.line_total == D(expected_total)


def test_fractional_gram_paise_boundary():
    """35g of loose cardamom @ ₹30/100g = 35 * 0.30 = ₹10.50 exactly."""
    res = calculate_line_price(
        quantity=35,
        requested_unit="g",
        selling_price=30,
        price_basis_quantity=100,
        price_basis_unit="g",
        inventory_unit="kg",
    )
    assert res.line_total == D("10.50")
    assert res.stock_deduction_quantity == D("0.035")


# ============================================================================
# Section F: Invalid Inputs & Error Handling
# ============================================================================


def test_zero_quantity_rejected():
    with pytest.raises(InvalidQuantityError, match="greater than 0"):
        calculate_line_price(quantity=0, requested_unit="kg", selling_price=50)


def test_negative_quantity_rejected():
    with pytest.raises(InvalidQuantityError, match="greater than 0"):
        calculate_line_price(quantity=-2, requested_unit="kg", selling_price=50)


def test_missing_price_rejected():
    with pytest.raises(InvalidPriceError, match="valid number"):
        calculate_line_price(quantity=1, requested_unit="kg", selling_price=None)


def test_negative_price_rejected():
    with pytest.raises(InvalidPriceError, match="cannot be negative"):
        calculate_line_price(quantity=1, requested_unit="kg", selling_price=-10)


def test_invalid_pricing_basis_qty_rejected():
    with pytest.raises(InvalidPricingBasisError, match="greater than 0"):
        calculate_line_price(
            quantity=1,
            requested_unit="kg",
            selling_price=50,
            price_basis_quantity=0,
            price_basis_unit="kg",
        )


def test_incompatible_dimensions_rejected():
    """Mass (kg) cannot be converted to Volume (L)."""
    with pytest.raises(IncompatiblePricingUnitsError, match="incompatible"):
        calculate_line_price(
            quantity=1,
            requested_unit="kg",
            selling_price=100,
            price_basis_unit="L",
        )


def test_pieces_to_weight_without_conversion_rejected():
    """Count (pcs) cannot be converted to Mass (kg) without explicit conversion."""
    with pytest.raises(IncompatiblePricingUnitsError, match="incompatible"):
        calculate_line_price(
            quantity=1,
            requested_unit="pcs",
            selling_price=50,
            price_basis_unit="kg",
        )


def test_unknown_unit_rejected():
    with pytest.raises(PricingEngineError, match="Unknown unit"):
        calculate_line_price(quantity=1, requested_unit="xyz_unknown", selling_price=50)


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf"), "nan", "inf", True, False])
def test_nan_infinity_boolean_rejected(bad_val):
    with pytest.raises(PricingEngineError):
        calculate_line_price(quantity=bad_val, requested_unit="kg", selling_price=50)
    with pytest.raises(PricingEngineError):
        calculate_line_price(quantity=1, requested_unit="kg", selling_price=bad_val)


# ============================================================================
# Section G: Wholesale Gate & Gating Statuses
# ============================================================================


def test_status_incomplete_rejected():
    with pytest.raises(PricingStatusError, match="incomplete pricing"):
        calculate_line_price(
            quantity=1,
            requested_unit="kg",
            selling_price=0,
            pricing_status="INCOMPLETE",
            product_name="Draft Item",
        )


def test_status_needs_review_rejected():
    with pytest.raises(PricingStatusError, match="requires manager pricing review"):
        calculate_line_price(
            quantity=1,
            requested_unit="pcs",
            selling_price=2050,
            pricing_status="NEEDS_REVIEW",
            product_name="Sugar",
        )


def test_wholesale_only_permits_whole_containers():
    """Wholesale sack of Chana: 1 bor @ ₹2,950 -> ₹2,950.00"""
    res = calculate_line_price(
        quantity=1,
        requested_unit="bor",
        selling_price=2950,
        price_basis_quantity=1,
        price_basis_unit="bor",
        inventory_unit="bor",
        pricing_status="WHOLESALE_ONLY",
        product_name="Chana 50 KG",
    )
    assert res.line_total == D("2950.00")
    assert res.stock_deduction_quantity == D("1")
    assert res.is_wholesale_only is True


def test_wholesale_only_rejects_fractional_container():
    """0.5 bor of Chana 50 KG is rejected."""
    with pytest.raises(InvalidQuantityError, match="fractional quantities"):
        calculate_line_price(
            quantity="0.5",
            requested_unit="bor",
            selling_price=2950,
            inventory_unit="bor",
            pricing_status="WHOLESALE_ONLY",
            product_name="Chana 50 KG",
        )


def test_wholesale_only_rejects_loose_unit():
    """1 kg requested of wholesale 50 kg sack is rejected."""
    with pytest.raises(PricingEngineError, match="wholesale-only and can only be sold in its configured container unit"):
        calculate_line_price(
            quantity=1,
            requested_unit="kg",
            selling_price=2950,
            inventory_unit="bor",
            pricing_status="WHOLESALE_ONLY",
            product_name="Chana 50 KG",
        )


# ============================================================================
# Section H: Client Price Assertion Verification
# ============================================================================


def test_client_assertion_matches_exactly():
    res = calculate_line_price(
        quantity=500,
        requested_unit="g",
        selling_price=48,
        price_basis_quantity=1,
        price_basis_unit="kg",
        client_unit_price="48.00",
    )
    assert res.line_total == D("24.00")


def test_client_assertion_matches_effective_rate():
    # Cardamom ₹30 per 100g -> rate is ₹0.30 per g
    res = calculate_line_price(
        quantity=250,
        requested_unit="g",
        selling_price=30,
        price_basis_quantity=100,
        price_basis_unit="g",
        client_unit_price="0.30",
    )
    assert res.line_total == D("75.00")


def test_client_assertion_price_tampering_rejected():
    with pytest.raises(PriceAssertionError, match="Price assertion failed"):
        calculate_line_price(
            quantity=1,
            requested_unit="kg",
            selling_price=48,
            client_unit_price="0.01",
            product_name="Sugar",
        )


# ============================================================================
# Section I: Purchase Cost and Statutory MRP
# ============================================================================


def test_purchase_cost_normalization():
    cost = calculate_purchase_cost(
        quantity=500,
        requested_unit="g",
        purchase_price=40,
        price_basis_quantity=1,
        price_basis_unit="kg",
    )
    assert cost.line_cost == D("20.00")
    assert cost.unit_cost == D("40.000")


def test_mrp_ceiling_compliance_and_savings():
    # Selling price ₹45, MRP ₹50
    mrp_eval = evaluate_mrp_ceiling(
        selling_price=45,
        mrp=50,
        quantity=2,
        price_basis_quantity=1,
    )
    assert mrp_eval.is_exceeded is False
    assert mrp_eval.line_mrp_total == D("100.00")
    assert mrp_eval.savings_amount == D("10.00")


def test_mrp_ceiling_exceeded_flag():
    # Selling price ₹55 exceeds statutory MRP ₹50
    mrp_eval = evaluate_mrp_ceiling(
        selling_price=55,
        mrp=50,
    )
    assert mrp_eval.is_exceeded is True
    assert mrp_eval.savings_amount is None


def test_loose_commodity_mrp_is_none():
    mrp_eval = evaluate_mrp_ceiling(
        selling_price=48,
        mrp=None,
    )
    assert mrp_eval.mrp_per_basis is None
    assert mrp_eval.line_mrp_total is None
    assert mrp_eval.is_exceeded is False


# ============================================================================
# Section J: Explicit Product Conversions (e.g. Unpacking Box)
# ============================================================================


def test_product_explicit_conversion_box_to_pcs():
    """Explicit conversion: 1 box = 12 pcs. Buy 1 box of a product priced per piece."""
    conv = ProductUnitConversion.create("box", "pcs", 12)
    res = calculate_line_price(
        quantity=1,
        requested_unit="box",
        selling_price=40,  # ₹40 per piece
        price_basis_quantity=1,
        price_basis_unit="pcs",
        inventory_unit="pcs",
        product_conversions=[conv],
        product_name="Biscuits",
    )
    assert res.line_total == D("480.00")  # 12 pcs * 40 = ₹480.00
    assert res.stock_deduction_quantity == D("12")  # 12 pcs deducted


# ============================================================================
# Section K: Determinism & Precision (No Float Leakage)
# ============================================================================


def test_repeated_calculation_determinism():
    results = [
        calculate_line_price(
            quantity="0.333",
            requested_unit="kg",
            selling_price="99.99",
            price_basis_quantity=1,
            price_basis_unit="kg",
        ).line_total
        for _ in range(100)
    ]
    assert all(r == results[0] for r in results)
    assert isinstance(results[0], Decimal)
