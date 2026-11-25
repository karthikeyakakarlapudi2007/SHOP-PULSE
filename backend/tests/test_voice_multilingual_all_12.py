import pytest
from services.voice_parser import extract_items_from_transcript, normalize_digits_and_numbers
from services.inventory_matcher import match_items_to_inventory
from api.routes.voice import SUPPORTED_LANGUAGES

def test_supported_languages_contains_all_12():
    codes = [lang["code"] for lang in SUPPORTED_LANGUAGES]
    assert len(codes) == 12
    expected_codes = [
        "en-IN", "hi-IN", "te-IN", "ta-IN", "kn-IN", "ml-IN",
        "mr-IN", "bn-IN", "gu-IN", "pa-IN", "or-IN", "as-IN"
    ]
    for code in expected_codes:
        assert code in codes

def test_all_10_indic_digits_scripts():
    samples = [
        ("Devanagari", "२ किलो चावल", "2 किलो चावल"),
        ("Telugu", "౨ కిలోల బియ్యం", "2 కిలోల బియ్యం"),
        ("Bengali", "২ কেজি চাল", "2 কেজি চাল"),
        ("Assamese", "২ কেজি চাউল", "2 কেজি চাউল"),
        ("Gujarati", "૨ કિલો ચોખા", "2 કિલો ચોખા"),
        ("Gurmukhi", "੨ ਕਿਲੋ ਚੌਲ", "2 ਕਿਲੋ ਚੌਲ"),
        ("Odia", "୨ କିଲୋ ଚାଉଳ", "2 କିଲୋ ଚାଉଳ"),
        ("Kannada", "೨ ಕಿಲೋ ಅಕ್ಕಿ", "2 ಕಿಲೋ ಅಕ್ಕಿ"),
        ("Malayalam", "൨ കിലോ അരി", "2 കിലോ അരി"),
        ("Tamil", "௨ கிலோ அரிசி", "2 கிலோ அரிசி"),
    ]
    for script_name, text, expected in samples:
        norm = normalize_digits_and_numbers(text)
        assert "2" in norm, f"Failed for {script_name}: {norm}"

def test_eight_target_utterances():
    catalog = [
        {
            "id": "prod-1",
            "name": "Basmati Rice (loose)",
            "selling_price": 60.0,
            "current_stock": 50,
            "unit": "kg",
            "category": "Staples",
            "pricing_status": "VERIFIED",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
        },
        {
            "id": "prod-2",
            "name": "Refined Sugar",
            "selling_price": 45.0,
            "current_stock": 40,
            "unit": "kg",
            "category": "Staples",
            "pricing_status": "VERIFIED",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "kg",
        },
        {
            "id": "prod-3",
            "name": "Toned Milk (500ml)",
            "selling_price": 28.0,
            "current_stock": 30,
            "unit": "packet",
            "category": "Dairy",
            "pricing_status": "VERIFIED",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "packet",
        },
        {
            "id": "prod-4",
            "name": "Sunflower Cooking Oil",
            "selling_price": 140.0,
            "current_stock": 25,
            "unit": "L",
            "category": "Oil",
            "pricing_status": "VERIFIED",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "L",
        },
        {
            "id": "prod-5",
            "name": "Lifebuoy Soap",
            "selling_price": 35.0,
            "current_stock": 60,
            "unit": "pcs",
            "category": "Personal Care",
            "pricing_status": "VERIFIED",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "pcs",
        },
        {
            "id": "prod-6",
            "name": "Parle-G",
            "selling_price": 10.0,
            "current_stock": 100,
            "unit": "packet",
            "category": "Snacks",
            "pricing_status": "VERIFIED",
            "price_basis_quantity": 1.0,
            "price_basis_unit": "packet",
        },
    ]

    # 1. "Give me 2 kilograms of rice."
    items = extract_items_from_transcript("Give me 2 kilograms of rice.")
    assert len(items) == 1
    assert items[0].name == "rice"
    assert items[0].quantity == 2
    assert items[0].unit == "kg"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Basmati Rice (loose)"
    assert matched[0].quantity == 2
    assert tot == 120.0

    # 2. "Add 500 grams of sugar."
    items = extract_items_from_transcript("Add 500 grams of sugar.")
    assert len(items) == 1
    assert items[0].name == "sugar"
    assert items[0].quantity == 500
    assert items[0].unit == "g"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Refined Sugar"
    assert matched[0].quantity == 0.5
    assert tot == 22.5

    # 3. "Give me 3 packets of milk."
    items = extract_items_from_transcript("Give me 3 packets of milk.")
    assert len(items) == 1
    assert items[0].name == "milk"
    assert items[0].quantity == 3
    assert items[0].unit == "packet"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Toned Milk (500ml)"
    assert matched[0].quantity == 3
    assert tot == 84.0

    # 4. "Add 2 litres of oil."
    items = extract_items_from_transcript("Add 2 litres of oil.")
    assert len(items) == 1
    assert items[0].name == "oil"
    assert items[0].quantity == 2
    assert items[0].unit == "L"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Sunflower Cooking Oil"
    assert matched[0].quantity == 2
    assert tot == 280.0

    # 5. "Give me 5 pieces of soap."
    items = extract_items_from_transcript("Give me 5 pieces of soap.")
    assert len(items) == 1
    assert items[0].name == "soap"
    assert items[0].quantity == 5
    assert items[0].unit == "pcs"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].name == "Lifebuoy Soap"
    assert matched[0].quantity == 5
    assert tot == 175.0

    # 6. "Add one packet of biscuits and two kilograms of rice."
    items = extract_items_from_transcript("Add one packet of biscuits and two kilograms of rice.")
    assert len(items) == 2
    assert items[0].name == "biscuit"
    assert items[0].quantity == 1
    assert items[0].unit == "packet"
    assert items[1].name == "rice"
    assert items[1].quantity == 2
    assert items[1].unit == "kg"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 2
    assert tot == 130.0

    # 7. "Remove one packet of sugar."
    items = extract_items_from_transcript("Remove one packet of sugar.")
    assert len(items) == 1
    assert items[0].name == "sugar"
    assert items[0].quantity == 1
    assert items[0].unit == "packet"
    assert items[0].action == "remove"

    # 8. "Change rice quantity to 3 kilograms."
    items = extract_items_from_transcript("Change rice quantity to 3 kilograms.")
    assert len(items) == 1
    assert items[0].name == "rice"
    assert items[0].quantity == 3
    assert items[0].unit == "kg"
    assert items[0].action == "update"
    matched, _, _, _, _, tot = match_items_to_inventory(items, catalog)
    assert len(matched) == 1
    assert matched[0].quantity == 3
    assert tot == 180.0
