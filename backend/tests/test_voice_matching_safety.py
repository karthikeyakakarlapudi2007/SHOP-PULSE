import pytest
from decimal import Decimal
from services.voice_parser import extract_items_from_transcript, ExtractedItem
from services.inventory_matcher import match_items_to_inventory, PRODUCT_CONCEPT_ALIASES

class MockProduct:
    def __init__(self, id: str, name: str, unit: str = "kg", price: float = 50.0, stock: float = 100.0,
                 category: str = "Grocery", price_basis_qty: float = 1.0, mrp: float = None):
        self.id = id
        self.name = name
        self.unit = unit
        self.selling_price = price
        self.current_stock = stock
        self.category = category
        self.price_basis_quantity = price_basis_qty
        self.price_basis_unit = unit
        self.pricing_status = "VERIFIED"
        self.mrp = mrp or price


# 1. Sugar vs Sugar-Free products
def test_confusable_sugar_vs_sugar_free():
    catalog = [
        MockProduct("p1", "Sugar", unit="kg", price=60.0),
        MockProduct("p2", "Sugar-Free Gold", unit="pcs", price=150.0, category="Health"),
    ]

    # Query for sugar -> must match Sugar, never Sugar-Free Gold
    items = extract_items_from_transcript("Give me 1 kg of sugar")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Sugar"
    assert len(ambig) == 0

    # Query for sugar-free -> must match Sugar-Free Gold, never Sugar
    items = extract_items_from_transcript("Give me 1 packet of sugar free")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Sugar-Free Gold"


# 2. Refined Sugar vs Brown Sugar
def test_confusable_refined_sugar_vs_brown_sugar():
    catalog = [
        MockProduct("p1", "Refined Sugar", unit="kg", price=50.0),
        MockProduct("p2", "Brown Sugar", unit="kg", price=90.0),
    ]

    items = extract_items_from_transcript("Give me 2 kg of brown sugar")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Brown Sugar"

    items = extract_items_from_transcript("Give me 2 kg of refined sugar")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Refined Sugar"


# 3. Rice vs Rice Flour
def test_confusable_rice_vs_rice_flour():
    catalog = [
        MockProduct("p1", "Rice", unit="kg", price=55.0),
        MockProduct("p2", "Rice Flour", unit="kg", price=45.0),
    ]

    # Query: rice
    items = extract_items_from_transcript("Give me 5 kg of rice")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Rice"

    # Query: rice flour
    items = extract_items_from_transcript("Give me 1 kg of rice flour")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Rice Flour"

    # Multilingual: Telugu బియ్యం -> Rice, not Rice Flour
    item_te = [ExtractedItem(name="బియ్యం", quantity=2, unit="kg")]
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(item_te, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Rice"

    # Multilingual: Hindi चावल -> Rice, not Rice Flour
    item_hi = [ExtractedItem(name="चावल", quantity=2, unit="kg")]
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(item_hi, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Rice"


# 4. Oil vs Essential Oil
def test_confusable_oil_vs_essential_oil():
    catalog = [
        MockProduct("p1", "Sunflower Cooking Oil", unit="L", price=160.0, category="Edible Oils"),
        MockProduct("p2", "Essential Oil", unit="pcs", price=350.0, category="Aromatherapy"),
    ]

    # Query: oil -> matches Cooking Oil, not Essential Oil
    items = extract_items_from_transcript("Give me 1 litre of oil")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Sunflower Cooking Oil"

    # Query: essential oil -> matches Essential Oil
    items = extract_items_from_transcript("Give me 1 bottle of essential oil")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Essential Oil"


# 5. Salt vs Black Salt
def test_confusable_salt_vs_black_salt():
    catalog = [
        MockProduct("p1", "Tata Salt", unit="pkt", price=28.0),
        MockProduct("p2", "Black Salt", unit="pkt", price=40.0),
    ]

    # Query: salt -> matches Tata Salt, not Black Salt
    items = extract_items_from_transcript("Give me 1 packet of salt")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Tata Salt"

    # Query: black salt -> matches Black Salt, not Tata Salt
    items = extract_items_from_transcript("Give me 1 packet of black salt")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Black Salt"


# 6. Tea vs Tea Powder
def test_confusable_tea_vs_tea_powder():
    catalog = [
        MockProduct("p1", "Tea", unit="packet", price=40.0),
        MockProduct("p2", "Tea Powder", unit="kg", price=320.0),
    ]

    # Query: tea
    items = extract_items_from_transcript("Give me 2 packets of tea")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Tea"

    # Query: tea powder
    items = extract_items_from_transcript("Give me 500 grams of tea powder")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Tea Powder"


# 7. Similar products from different brands -> Must return Ambiguous, never silent choice
def test_different_brands_ambiguity():
    catalog = [
        MockProduct("p1", "Tata Salt 1kg", unit="pkt", price=28.0),
        MockProduct("p2", "Aashirvaad Salt 1kg", unit="pkt", price=26.0),
    ]

    # Spoken generic "salt"
    items = extract_items_from_transcript("Give me 1 packet of salt")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 0
    assert len(ambig) == 1
    cand_names = [c.name for c in ambig[0].candidates]
    assert "Tata Salt 1kg" in cand_names
    assert "Aashirvaad Salt 1kg" in cand_names

    # Spoken brand-specific "Tata Salt"
    items = extract_items_from_transcript("Give me 1 packet of tata salt")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Tata Salt 1kg"


# 8. Multiple products sharing same concept alias -> Ambiguity, never arbitrary choice
def test_multiple_products_same_concept_ambiguity():
    catalog = [
        MockProduct("p1", "Basmati Rice 1kg", unit="kg", price=90.0),
        MockProduct("p2", "Sona Masoori Rice 1kg", unit="kg", price=65.0),
    ]

    # Spoken generic "rice"
    items = extract_items_from_transcript("Give me 2 kg of rice")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 0
    assert len(ambig) == 1
    assert len(ambig[0].candidates) == 2

    # Spoken specific "basmati rice"
    items = extract_items_from_transcript("Give me 2 kg of basmati rice")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Basmati Rice 1kg"


# 9. Safety against unmatched descriptive modifiers (e.g. asking for Brown Sugar when store only has Sugar)
def test_unmatched_descriptive_modifier_safety():
    catalog = [
        MockProduct("p1", "Sugar", unit="kg", price=60.0),
    ]

    # Customer asks for "brown sugar", store only has plain "Sugar"
    # System must NOT silently sell plain sugar!
    items = extract_items_from_transcript("Give me 1 kg of brown sugar")
    matched, ambig, unmatched, _, _, _ = match_items_to_inventory(items, catalog)
    assert len(matched) == 0
    # Must flag ambiguity or unmatched
    assert len(ambig) == 1 or len(unmatched) == 1


# 10. Fractional pricing calculations after matching
def test_fractional_pricing_after_matching():
    catalog = [
        MockProduct("p1", "Refined Sugar", unit="kg", price=60.0, price_basis_qty=1.0),
        MockProduct("p2", "Sunflower Cooking Oil", unit="L", price=160.0, price_basis_qty=1.0),
    ]

    # 500g of sugar at ₹60/kg = ₹30.00
    items = extract_items_from_transcript("Give me 500 grams of sugar")
    matched, _, _, subtotal, _, total = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].quantity == 0.5
    assert matched[0].total_price == 30.0

    # 250ml of oil at ₹160/L = ₹40.00
    items = extract_items_from_transcript("Give me 250 ml of oil")
    matched, _, _, subtotal, _, total = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].quantity == 0.25
    assert matched[0].total_price == 40.0


# 11. Multilingual alias coverage across configured Indian languages
def test_multilingual_indian_language_aliases():
    catalog = [
        MockProduct("p1", "Rice", unit="kg", price=50.0),
        MockProduct("p2", "Tata Salt", unit="kg", price=25.0),
        MockProduct("p3", "Refined Sugar", unit="kg", price=45.0),
    ]

    multilingual_queries = [
        ("Telugu", "బియ్యం", "Rice"),
        ("Telugu", "ఉప్పు", "Tata Salt"),
        ("Telugu", "పంచదార", "Refined Sugar"),
        ("Hindi", "चावल", "Rice"),
        ("Hindi", "नमक", "Tata Salt"),
        ("Hindi", "चीनी", "Refined Sugar"),
        ("Tamil", "அரிசி", "Rice"),
        ("Kannada", "ಅಕ್ಕಿ", "Rice"),
        ("Malayalam", "അരി", "Rice"),
        ("Marathi", "तांदूळ", "Rice"),
        ("Bengali", "চাল", "Rice"),
        ("Gujarati", "ચોખા", "Rice"),
        ("Punjabi", "ਚੌਲ", "Rice"),
        ("Odia", "ଚାଉଳ", "Rice"),
        ("Assamese", "চাউল", "Rice"),
    ]

    for lang, word, expected_product in multilingual_queries:
        item = [ExtractedItem(name=word, quantity=1, unit="kg")]
        matched, ambig, unmatched, _, _, _ = match_items_to_inventory(item, catalog)
        assert len(matched) == 1, f"Failed for {lang} '{word}': expected {expected_product}"
        assert matched[0].name == expected_product, f"Mismatch for {lang} '{word}': got {matched[0].name}"
