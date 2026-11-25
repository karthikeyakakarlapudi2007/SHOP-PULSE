from decimal import Decimal
import re
from typing import List, Tuple, Any, Optional
from uuid import UUID

from schemas.voice import (
    VoiceProductCandidate,
    MatchedVoiceItem,
    AmbiguousVoiceItem,
    UnmatchedVoiceItem,
)
from services.voice_parser import ExtractedItem, canonical_voice_unit
from services.money import bill_total, quantize_half_up, round_currency, round_price, sale_line_amount, to_decimal, to_number
from services.pricing_engine import calculate_line_price, PricingEngineError, evaluate_mrp_ceiling
from services.stock import format_quantity, quantity_number, to_stock_quantity
from services.unit_registry import FAMILIES, UNITS, UnitError, convert_quantity, try_normalize_unit


class VoiceItemError(ValueError):
    """A spoken line that cannot be sold as said (incompatible unit, fraction of a whole-number unit, ...).
    It is reported as unmatched with this reason; nothing is guessed."""

def normalize_text_for_search(text: str) -> str:
    """Removes punctuation and lowercases text for fuzzy token search while preserving Indic scripts."""
    cleaned = re.sub(r"[^a-zA-Z0-9\sऀ-ൿ]", " ", text)
    return " ".join(cleaned.lower().split())

PRODUCT_CONCEPT_ALIASES = {
    "Rice": [
        "rice", "basmati rice", "chawal", "white rice", "brown rice",
        "బియ్యం", "బాస్మతి బియ్యం", "రైస్",
        "चावल", "बासमती चावल", "राइस",
        "அரிசி", "பாஸ்மதி அரிசி",
        "ಅಕ್ಕಿ", "ಬಾಸ್ಮತಿ ಅಕ್ಕಿ",
        "അരി", "ബസ്മതി അരി",
        "तांदूळ", "बासमती तांदूळ", "भात",
        "চাল", "বাসমতী চাল",
        "ચોખા", "બાસમતી ચોખા",
        "ਚੌਲ", "ਬਾਸਮਤੀ ਚੌਲ",
        "ଚାଉଳ", "ବାସମତୀ ଚାଉଳ",
        "চাউল", "বাসমতী চাউল"
    ],
    "Tata Salt": [
        "tata salt", "tata salt 1kg", "salt", "iodized salt",
        "టాటా సాల్ట్", "టాటా ఉప్పు", "ఉప్పు", "సాల్ట్",
        "टाटा नमक", "टाटा साल्ट", "नमक", "साल्ट",
        "டாடா உப்பு", "டாடா சால்ட்",
        "ಟಾಟಾ ಉಪ್ಪು", "ಟಾಟಾ ಸಾಲ್ಟ್",
        "ടാറ്റ ഉപ്പ്", "ടാറ്റ സോൾട്ട്",
        "टाटा मीठ", "टाटा सॉल्ट", "मीठ",
        "টাটা লবণ", "টাটা নুন", "লবণ", "নুন",
        "ટાટા મીઠું", "ટાટા સોલ્ટ", "મીઠું",
        "ਟਾਟਾ ਲੂਣ", "ਟਾਟਾ ਸਾਲਟ", "ਲੂਣ",
        "ଟାଟା ଲୁଣ", "ଲୁଣ",
        "টাটা নিমখ", "নিমখ"
    ],
    "Parle-G": [
        "parle-g", "parle g", "parleg", "parle g biscuits", "biscuits",
        "పార్లే-జి", "పార్లే జి", "పార్లే జీ", "బిస్కెట్లు", "బిస్కట్",
        "पारले-जी", "पारले जी", "पारलेजी", "बिस्कुट",
        "பார்லே-ஜி", "பார்லே ஜி", "பிஸ்கட்",
        "ಪಾರ್ಲೆ-ಜಿ", "ಪಾರ್ಲೆ ಜಿ", "ಬಿಸ್ಕತ್ತು",
        "പാർലെ-ജി", "പാർലെ ജി", "ബിസ്‌ക്കറ്റ്",
        "पारले-जी", "पारले जी", "बिस्कीट",
        "পার্লে-জি", "পার্লে জি", "বিস্কুট",
        "પાર્લે-જી", "પાર્લે જી", "બિસ્કિટ",
        "ਪਾਰਲੇ-ਜੀ", "ਪਾਰਲੇ ਜੀ", "ਬਿਸਕੁਟ",
        "ପାର୍ଲେ-ଜି", "ପାର୍ଲେ ଜି", "ବିସ୍କୁଟ",
        "পাৰ্লে-জি", "পাৰ্লে জি", "বিস্কুট"
    ],
    "Aashirvaad Atta": [
        "aashirvaad atta", "ashirvad atta", "atta", "wheat flour", "flour",
        "ఆశీర్వాద్ గోధుమ పిండి", "ఆశీర్వాద్ పిండి", "ఆశీర్వాద్ ఆటా", "గోధుమ పిండి", "పిండి", "ఆటా",
        "आशीर्वाद आटा", "आटा", "गेहूं का आटा",
        "ஆசீர்வாத் கோதுமை மாவு", "ஆசீர்வாத் மாவு", "கோதுமை மாவு", "மாவு",
        "ಆಶೀರ್ವಾದ್ ಗೋಧಿ ಹಿಟ್ಟು", "ಆಶೀರ್ವಾದ್ ಹಿಟ್ಟು", "ಗೋಧಿ ಹಿಟ್ಟು", "ಹಿಟ್ಟು",
        "ആശീർവാദ് ഗോതമ്പ് മാവ്", "ഗോതമ്പ് മാവ്",
        "आशीर्वाद आटा", "गव्हाचे पीठ", "आटा",
        "আশীর্বাদ আটা", "গম আটা", "আটা",
        "આશીર્વાદ લોટ", "ઘઉંનો લોਟ", "લોટ",
        "ਆਸ਼ੀਰਵਾਦ ਆਟਾ", "ਕਣਕ ਦਾ ਆਟਾ", "ਆਟਾ",
        "ଆଶୀର୍ବାଦ ଅଟା", "ଗହମ ଅଟା", "ଅଟା",
        "আশীৰ্বাদ আটা", "আটা"
    ],
    "Toned Milk": [
        "toned milk", "toned milk (500ml)", "milk", "amul milk",
        "టోన్డ్ పాలు", "పాలు", "మిల్క్",
        "टोन्ड दूध", "दूध", "मिल्क",
        "டோன்ட் பால்", "பால்",
        "ಟೋನ್ಡ್ ಹಾಲು", "ಹಾಲು",
        "ടോൺഡ് പാൽ", "പാൽ",
        "टोन्ड दूध", "दूध",
        "টোনড দুধ", "দুধ",
        "ટોન્ડ દૂધ", "દૂધ",
        "ਟੋਨਡ ਦੁੱਧ", "ਦੁੱਧ",
        "ଟୋନଡ୍ କ୍ଷୀର", "କ୍ଷୀର",
        "টোনড গাখীৰ", "গাখীৰ"
    ],
    "Fresh White Bread": [
        "fresh white bread", "white bread", "bread", "loaf of bread",
        "వైట్ బ్రెడ్", "బ్రెడ్",
        "व्हाइट ब्रेड", "ब्रेड",
        "வெள்ளை ரொட்டி", "ரொட்டி", "பிரெட்",
        "ವೈಟ್ ಬ್ರೆಡ್", "ಬ್ರೆಡ್",
        "വൈറ്റ് ബ്രെഡ്", "ബ്രെഡ്",
        "व्हाईट ब्रेड", "ब्रेड",
        "সাদা পাউরুটি", "পাউরুটি",
        "વ્હાઇટ બ્રેડ", "બ્રેડ",
        "ਵਾਈਟ ਬਰੈੱਡ", "ਬਰੈੱਡ",
        "ହ୍ୱାଇଟ୍ ବ୍ରେଡ୍", "ବ୍ରେଡ୍",
        "বগা পাউৰুটী", "পাউৰুটী"
    ],
    "Refined Sugar": [
        "refined sugar", "sugar", "sugar (1kg)",
        "చక్కెర", "పంచదార", "షుగర్",
        "चीनी", "शक्कर", "शुगर",
        "சர்க்கரை", "சீனி",
        "ಸಕ್ಕರೆ",
        "പഞ്ചസാര",
        "साखर",
        "চিনি",
        "ખાંડ",
        "ਖੰਡ",
        "ଚିନି",
        "চেনি"
    ],
    "Sunflower Cooking Oil": [
        "sunflower cooking oil", "sunflower oil", "oil", "cooking oil",
        "సన్‌ఫ్లవర్ నూనె", "వంట నూనె", "నూనె", "ఆయిల్",
        "सनफ्लावर तेल", "खाना पकाने का तेल", "तेल", "ऑयल",
        "சூரியகாந்தி எண்ணெய்", "சமையல் எண்ணெய்", "எண்ணெய்",
        "ಸೂರ್ಯಕಾಂತಿ ಎಣ್ಣೆ", "ಅಡುಗೆ ಎಣ್ಣೆ", "ಎಣ್ಣೆ",
        "സൂര്യകാന്തി എണ്ണ", "പാചക എണ്ണ", "എണ്ണ",
        "सूर्यफूल तेल", "खाद्यतेल", "तेल",
        "সূর্যমুখী তেল", "রান্নার তেল", "তেল",
        "સૂર્યમુખી તેલ", "તેલ",
        "ਸੂਰਜਮੁਖੀ ਤੇਲ", "ਤੇਲ",
        "ସୂର୍ଯ୍ୟମୁଖୀ ତେଲ", "ତେଲ",
        "সূৰ্য্যমুখী তেল", "তেল"
    ],
    "Premium Assam Tea": [
        "premium assam tea", "assam tea", "tea", "tea powder",
        "అస్సాం టీ", "టీ", "చాయ్", "టీ పొడి",
        "असम चाय", "चाय", "चाय पत्ती",
        "அசாம் தேநீர்", "தேநீர்", "டீ",
        "ಅಸ್ಸಾಂ ಚಹಾ", "ಚಹಾ", "ಟೀ",
        "അസം ചായ", "ചായ",
        "आसाम चहा", "चहा",
        "আসাম চা", "চা",
        "આસામ ચા", "ચા",
        "ਅਸਾਮ ਚਾਹ", "ਚਾਹ",
        "ଆସାମ ଚା", "ଚା",
        "অসম চাহ", "চাহ"
    ],
    "Coca Cola": [
        "coca cola", "coke", "cola", "cold drink",
        "కోకా కోలా", "కోక్", "కూల్ డ్రింక్",
        "कोका कोला", "कोक", "कोल्ड ड्रिंक",
        "கோகோ கோலா", "கோக்",
        "ಕೋಕಾ ಕೋಲಾ", "ಕೋಕ್",
        "കൊക്കകോള", "കോക്ക്",
        "कोका कोला", "कोक",
        "কোকা কোলা", "কোক",
        "કોકા કોલા", "કોક",
        "ਕੋਕਾ ਕੋਲਾ", "ਕੋਕ",
        "କୋକା କୋଲା", "କୋକ୍",
        "কোকা কোলা", "কোক"
    ]
}

def to_candidate(p: Any) -> VoiceProductCandidate:
    """Converts a database Product or candidate model/dict to a uniform VoiceProductCandidate."""
    if isinstance(p, VoiceProductCandidate):
        return p
    if hasattr(p, "id"):
        basis_qty = getattr(p, "price_basis_quantity", None)
        basis_qty = float(basis_qty) if basis_qty is not None else 1.0
        basis_unit = getattr(p, "price_basis_unit", None)
        mrp_basis_qty = getattr(p, "mrp_basis_quantity", None)
        mrp_basis_unit = getattr(p, "mrp_basis_unit", None)
        status = getattr(p, "pricing_status", None)
        mrp = getattr(p, "mrp", None)
        return VoiceProductCandidate(
            id=str(p.id),
            name=p.name,
            selling_price=float(p.selling_price if hasattr(p, "selling_price") else getattr(p, "price", 0.0)),
            current_stock=quantity_number(p.current_stock if hasattr(p, "current_stock") else getattr(p, "stock", 0)),
            unit=str(p.unit or "pcs"),
            category=getattr(p, "category", None),
            sku=getattr(p, "sku", None),
            price_basis_quantity=basis_qty,
            price_basis_unit=str(basis_unit) if basis_unit else str(p.unit or "pcs"),
            mrp_basis_quantity=float(mrp_basis_qty) if mrp_basis_qty is not None else None,
            mrp_basis_unit=str(mrp_basis_unit) if mrp_basis_unit else None,
            pricing_status=str(status) if status else "NEEDS_REVIEW",
            mrp=float(mrp) if mrp is not None else None,
        )
    basis_qty = p.get("price_basis_quantity")
    basis_qty = float(basis_qty) if basis_qty is not None else 1.0
    basis_unit = p.get("price_basis_unit")
    mrp_basis_qty = p.get("mrp_basis_quantity")
    mrp_basis_unit = p.get("mrp_basis_unit")
    status = p.get("pricing_status")
    mrp = p.get("mrp")
    return VoiceProductCandidate(
        id=str(p["id"]),
        name=p["name"],
        selling_price=float(p.get("selling_price", p.get("price", 0.0))),
        current_stock=quantity_number(p.get("current_stock", p.get("stock", 0))),
        unit=str(p.get("unit", "pcs")),
        category=p.get("category"),
        sku=p.get("sku"),
        price_basis_quantity=basis_qty,
        price_basis_unit=str(basis_unit) if basis_unit else str(p.get("unit", "pcs")),
        mrp_basis_quantity=float(mrp_basis_qty) if mrp_basis_qty is not None else None,
        mrp_basis_unit=str(mrp_basis_unit) if mrp_basis_unit else None,
        pricing_status=str(status) if status else "VERIFIED",
        mrp=float(mrp) if mrp is not None else None,
    )

# Precision of the exact unit price derived from a spoken total (so quantity x price reproduces the total)
_EXACT_UNIT_PRICE = Decimal("0.0000000001")

WEIGHT_AND_CONTAINER_TOKENS = {
    "1kg", "2kg", "5kg", "10kg", "500g", "250g", "200g", "100g", "50g",
    "1l", "2l", "5l", "500ml", "250ml", "200ml", "100ml",
    "kg", "g", "gm", "gms", "l", "ltr", "liter", "liters", "litre", "litres", "ml",
    "packet", "packets", "pkt", "pkts", "pack", "packs", "pcs", "piece", "pieces",
    "bottle", "bottles", "can", "cans", "box", "boxes", "tin", "tins", "pouch", "pouches",
    "loose", "bag", "bags"
}

DISTINGUISHING_MODIFIERS = {"flour", "powder", "free", "brown", "black", "essential", "cream", "hair"}

PRODUCT_CONCEPT_COMMODITY_TOKENS = {
    "Rice": {"rice"},
    "Tata Salt": {"salt"},
    "Refined Sugar": {"sugar"},
    "Sunflower Cooking Oil": {"oil"},
    "Premium Assam Tea": {"tea"},
    "Toned Milk": {"milk"},
    "Fresh White Bread": {"bread"},
    "Aashirvaad Atta": {"atta"},
    "Parle-G": {"parle", "biscuit"},
    "Coca Cola": {"cola", "coke"},
}

def stem_token(t: str) -> str:
    """Normalizes simple English plurals for token-level matching."""
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t

def query_matches_alias(query_norm: str, alias_norm: str) -> bool:
    """Matches a spoken query against an alias using token awareness to prevent substring bleed."""
    if query_norm == alias_norm:
        return True
    q_tokens = query_norm.split()
    a_tokens = alias_norm.split()
    if set(q_tokens) == set(a_tokens):
        return True
    q_stemmed = {stem_token(t) for t in q_tokens if t not in WEIGHT_AND_CONTAINER_TOKENS}
    a_stemmed = {stem_token(t) for t in a_tokens if t not in WEIGHT_AND_CONTAINER_TOKENS}
    if q_stemmed and q_stemmed == a_stemmed:
        return True
    return False

def candidate_matches_concept(cand: VoiceProductCandidate, concept_name: str, aliases: List[str]) -> bool:
    """Checks if a catalog candidate product corresponds to a generic concept without false-positive bleed."""
    c_norm = normalize_text_for_search(cand.name)
    concept_norm = normalize_text_for_search(concept_name)
    alias_norms = [normalize_text_for_search(a) for a in aliases]

    if c_norm == concept_norm or c_norm in alias_norms:
        return True

    c_tokens = set(c_norm.split())
    c_stemmed = {stem_token(t) for t in c_tokens if t not in WEIGHT_AND_CONTAINER_TOKENS}

    for a_norm in [concept_norm] + alias_norms:
        a_stemmed = {stem_token(t) for t in a_norm.split() if t not in WEIGHT_AND_CONTAINER_TOKENS}
        if c_stemmed and c_stemmed == a_stemmed:
            return True

    # Commodity subset matching: e.g. "Sona Masoori Rice 1kg" matches generic concept "Rice"
    commodity_tokens = PRODUCT_CONCEPT_COMMODITY_TOKENS.get(concept_name)
    if commodity_tokens and any(t in c_stemmed for t in commodity_tokens):
        extra_modifiers = c_stemmed & DISTINGUISHING_MODIFIERS
        if not extra_modifiers:
            return True

    concept_tokens = {stem_token(t) for t in concept_norm.split() if t not in WEIGHT_AND_CONTAINER_TOKENS}
    if concept_tokens and concept_tokens.issubset(c_stemmed):
        extra_modifiers = (c_stemmed - concept_tokens) & DISTINGUISHING_MODIFIERS
        if not extra_modifiers:
            return True

    if cand.category:
        cat_norm = normalize_text_for_search(str(cand.category))
        if concept_norm in cat_norm:
            extra_modifiers = c_stemmed & DISTINGUISHING_MODIFIERS
            if not extra_modifiers:
                return True

    return False


def _kind(unit_id: str) -> str:
    return FAMILIES[UNITS[unit_id].family].kind


def _colloquial(spoken: Optional[str], target: Optional[str]) -> bool:
    """Spoken count/package word for a product counted in another count/package unit ("3 tea packets" of a
    product stocked in pcs): one spoken item is one product unit. Measures (kg, g, L, ml) always convert."""
    return bool(spoken and target and spoken != target and UNITS[spoken].family != UNITS[target].family
                and _kind(spoken) != "measure" and _kind(target) != "measure")


def _spoken_unit(item: ExtractedItem) -> Optional[str]:
    return canonical_voice_unit(getattr(item, "unit", None))


def _stock_quantity(prod: VoiceProductCandidate, item: ExtractedItem) -> Decimal:
    """Spoken quantity in the product's stock unit: 500 g of a kg product -> 0.5. Incompatible units
    (L for a kg product) and fractions of whole-number units are refused, never guessed."""
    spoken = _spoken_unit(item)
    product_unit = try_normalize_unit(prod.unit) if prod.unit else None
    given = spoken
    if spoken and product_unit is None:
        given = spoken if _kind(spoken) == "measure" else None
    elif _colloquial(spoken, product_unit):
        given = None
    try:
        return to_stock_quantity(item.quantity, given, prod)
    except ValueError as exc:
        raise VoiceItemError(str(exc)) from None


def _quantity_for_price(item: ExtractedItem, prod: VoiceProductCandidate) -> Decimal:
    """Quantity in the unit a spoken unit price is per ("45 rupees per kg" for 500 g -> 0.5)."""
    qty = to_decimal(item.quantity)
    spoken = _spoken_unit(item) or (try_normalize_unit(prod.unit) if prod.unit else None)
    per = canonical_voice_unit(getattr(item, "price_unit", None))
    if per is None or spoken is None or per == spoken or _colloquial(spoken, per):
        return qty  # "each": per spoken unit
    try:
        return convert_quantity(qty, spoken, per)
    except UnitError as exc:
        raise VoiceItemError(f"'{prod.name}': the price is per {UNITS[per].label}, but {exc}") from None


def make_matched_item(prod: VoiceProductCandidate, item: ExtractedItem) -> MatchedVoiceItem:
    """The sale line for a spoken item. Resolves price and stock deduction authoritatively via PricingEngine.
    A spoken price agreement is kept with price_source='spoken' and validated against statutory MRP.

    Raises VoiceItemError when the line cannot be sold as said (unverified status, incomplete pricing,
    wholesale violation, incompatible units, MRP exceeded)."""
    # 1. Gate check product pricing status
    status = str(prod.pricing_status or "VERIFIED").strip().upper()
    if status == "NEEDS_REVIEW":
        raise VoiceItemError(f"Product '{prod.name}' requires manager pricing review before checkout.")
    if status == "INCOMPLETE":
        raise VoiceItemError(f"Product '{prod.name}' has incomplete pricing (₹0.00). Cannot be sold.")

    spoken = _spoken_unit(item)
    product_unit = try_normalize_unit(prod.unit) if prod.unit else None

    # 2. Strict Wholesale Container Validation
    if status == "WHOLESALE_ONLY":
        req_u = spoken or product_unit or "pcs"
        norm_req = try_normalize_unit(req_u)
        norm_inv = product_unit
        if norm_req != norm_inv:
            raise VoiceItemError(f"Product '{prod.name}' is wholesale-only. Must purchase in '{prod.unit}', not in '{req_u}'.")
        qty_dec = to_decimal(item.quantity)
        if qty_dec != qty_dec.to_integral_value():
            raise VoiceItemError(f"Product '{prod.name}' is wholesale-only. Must purchase whole containers, not fractional ({item.quantity}).")

    # 3. Determine requested unit (respecting colloquial count units like packet of pcs)
    if spoken and product_unit and _colloquial(spoken, product_unit):
        req_unit = product_unit
    else:
        req_unit = spoken or product_unit or "pcs"

    # 4. Universal Decimal Pricing Engine Calculation
    basis_qty = prod.price_basis_quantity if prod.price_basis_quantity is not None else Decimal("1.0")
    basis_unit = prod.price_basis_unit if prod.price_basis_unit else prod.unit

    try:
        pricing_result = calculate_line_price(
            quantity=item.quantity,
            requested_unit=req_unit,
            selling_price=prod.selling_price,
            price_basis_quantity=basis_qty,
            price_basis_unit=basis_unit,
            inventory_unit=prod.unit,
            product_conversions=None,
            client_unit_price=None,
            pricing_status=status,
            product_name=prod.name,
            mrp=prod.mrp,
            mrp_basis_quantity=getattr(prod, "mrp_basis_quantity", None),
            mrp_basis_unit=getattr(prod, "mrp_basis_unit", None),
        )
    except PricingEngineError as exc:
        raise VoiceItemError(str(exc)) from None
    except ValueError as exc:
        raise VoiceItemError(str(exc)) from None

    qty = pricing_result.stock_deduction_quantity
    catalog_line_total = pricing_result.line_total

    # 5. Evaluate Spoken Price vs Catalog Price
    spoken_total = to_decimal(getattr(item, "spoken_price", None))
    spoken_unit_price = to_decimal(getattr(item, "spoken_unit_price", None))

    if spoken_total is not None and spoken_total > 0:
        line = round_currency(spoken_total)
        source = "spoken"
    elif spoken_unit_price is not None and spoken_unit_price > 0:
        line = sale_line_amount(_quantity_for_price(item, prod), spoken_unit_price)
        source = "spoken"
    else:
        line = catalog_line_total
        source = "catalogue"

    # 6. Statutory MRP Ceiling Enforcement for Spoken Prices (Legal Metrology Act)
    if source == "spoken" and pricing_result.line_mrp_total is not None:
        if line > pricing_result.line_mrp_total:
            raise VoiceItemError(
                f"Spoken price ₹{to_number(line)} for '{prod.name}' exceeds statutory MRP ₹{to_number(pricing_result.line_mrp_total)}."
            )

    # 7. Unit price formatting
    if source == "spoken":
        exact = quantize_half_up(line / qty, _EXACT_UNIT_PRICE)
        shown = round_price(exact)
    else:
        exact = pricing_result.effective_unit_price
        shown = round_price(exact)

    said = f"{format_quantity(item.quantity)} {UNITS[spoken].label}" if spoken else None
    stocked = f"{format_quantity(qty)} {prod.unit}"

    return MatchedVoiceItem(
        product_id=prod.id,
        name=prod.name,
        quantity=quantity_number(qty),
        unit_price=to_number(shown),
        unit_price_exact=to_number(exact),
        total_price=to_number(line),
        unit=prod.unit,
        current_stock=prod.current_stock,
        is_out_of_stock=prod.current_stock <= 0,
        is_insufficient_stock=float(qty) > prod.current_stock,
        available_stock=max(0, prod.current_stock),
        price_source=source,
        spoken_quantity=said if said and said != stocked else None,
        pricing_status=status,
        mrp=to_number(pricing_result.line_mrp_total) if pricing_result.line_mrp_total is not None else (float(prod.mrp) if prod.mrp is not None else None),
        catalog_line_total=to_number(catalog_line_total),
    )


def match_items_to_inventory(
    extracted_items: List[ExtractedItem],
    catalog: List[Any],
) -> Tuple[List[MatchedVoiceItem], List[AmbiguousVoiceItem], List[UnmatchedVoiceItem], float, float, float]:
    """
    Matches extracted natural language items against inventory products.
    Returns: (matched_items, ambiguous_items, unmatched_items, subtotal, tax, total).
    """
    candidates_catalog = [to_candidate(p) for p in catalog]

    matched_items: List[MatchedVoiceItem] = []
    ambiguous_items: List[AmbiguousVoiceItem] = []
    unmatched_items: List[UnmatchedVoiceItem] = []

    def add_match(prod: VoiceProductCandidate, item: ExtractedItem) -> None:
        try:
            matched_items.append(make_matched_item(prod, item))
        except VoiceItemError as exc:
            # Cannot be sold as said: shown for correction, never turned into a different sale
            unmatched_items.append(UnmatchedVoiceItem(queried_name=item.name, quantity=item.quantity, reason=str(exc)))

    def add_ambiguous(item: ExtractedItem, cands: List[VoiceProductCandidate]) -> None:
        options = []
        for cand in cands:
            try:
                options.append(make_matched_item(cand, item))
            except VoiceItemError:
                pass  # this candidate cannot be sold as said; the others stay selectable
        spoken = to_decimal(getattr(item, "spoken_price", None))
        ambiguous_items.append(AmbiguousVoiceItem(
            queried_name=item.name, quantity=item.quantity, candidates=cands,
            spoken_price=to_number(round_currency(spoken)) if spoken is not None and spoken > 0 else None,
            options=options,
        ))

    weights = ["1kg", "500g", "200g", "5kg", "100g", "400g", "1l", "2l"]

    for item in extracted_items:
        query_norm = normalize_text_for_search(item.name)
        if not query_norm:
            continue

        q_tokens = [w for w in query_norm.split() if len(w) > 1]
        query_weights = [w for w in weights if w in query_norm]
        
        # 1. Exact Catalog Match (Highest Priority)
        exact_matches = [
            c for c in candidates_catalog 
            if normalize_text_for_search(c.name) == query_norm
        ]

        if len(exact_matches) == 1:
            add_match(exact_matches[0], item)
            continue
        elif len(exact_matches) > 1:
            if query_weights:
                variant_filtered = [
                    c for c in exact_matches
                    if any(w in normalize_text_for_search(c.name) for w in query_weights)
                ]
                if len(variant_filtered) == 1:
                    add_match(variant_filtered[0], item)
                    continue
            add_ambiguous(item, exact_matches)
            continue

        # 2. Multilingual Concept Alias Search (Token-Aware)
        alias_matched_prod = None
        for concept_name, aliases in PRODUCT_CONCEPT_ALIASES.items():
            if any(query_matches_alias(query_norm, normalize_text_for_search(a)) for a in aliases):
                c_matches = [
                    c for c in candidates_catalog
                    if candidate_matches_concept(c, concept_name, aliases)
                ]
                if len(c_matches) == 1:
                    alias_matched_prod = c_matches[0]
                    break
                elif len(c_matches) > 1:
                    q_meaningful = [stem_token(t) for t in q_tokens if t not in WEIGHT_AND_CONTAINER_TOKENS]
                    if len(q_meaningful) > 1:
                        specific_matches = [
                            c for c in c_matches 
                            if set(q_meaningful).issubset({stem_token(t) for t in normalize_text_for_search(c.name).split() if t not in WEIGHT_AND_CONTAINER_TOKENS})
                        ]
                        if len(specific_matches) == 1:
                            alias_matched_prod = specific_matches[0]
                            break
                        elif len(specific_matches) > 1:
                            c_matches = specific_matches
                    if query_weights:
                        weight_match = next((c for c in c_matches if any(w in normalize_text_for_search(c.name) and w in query_weights for w in query_weights)), None)
                        if weight_match:
                            alias_matched_prod = weight_match
                            break
                    add_ambiguous(item, c_matches)
                    alias_matched_prod = "AMBIGUOUS"
                    break

        if alias_matched_prod == "AMBIGUOUS":
            continue
        elif alias_matched_prod:
            add_match(alias_matched_prod, item)
            continue

        # 3. Token containment search (all tokens of query must be present in candidate)
        all_token_matches = []
        for c in candidates_catalog:
            c_norm = normalize_text_for_search(c.name)
            c_tokens = set(c_norm.split())
            if all(token in c_tokens or any(token in ct for ct in c_tokens) for token in q_tokens):
                all_token_matches.append(c)

        if len(all_token_matches) > 1 and query_weights:
            variant_filtered = [
                c for c in all_token_matches
                if any(w in normalize_text_for_search(c.name) for w in query_weights)
            ]
            if len(variant_filtered) == 1:
                all_token_matches = variant_filtered

        if len(all_token_matches) == 1:
            add_match(all_token_matches[0], item)
            continue
        elif len(all_token_matches) > 1:
            add_ambiguous(item, all_token_matches)
            continue

        # 4. Partial overlap search with safety check
        scored_matches = []
        for c in candidates_catalog:
            c_norm = normalize_text_for_search(c.name)
            c_tokens = set(c_norm.split())
            match_count = sum(1 for token in q_tokens if token in c_tokens or any(token in ct for ct in c_tokens))
            if match_count > 0:
                scored_matches.append((match_count, c))

        if scored_matches:
            scored_matches.sort(key=lambda x: -x[0])
            max_score = scored_matches[0][0]
            # Must match at least 60% of query tokens
            best_candidates = [
                c for score, c in scored_matches 
                if score == max_score and score >= len(q_tokens) * 0.6
            ]

            if len(best_candidates) > 1 and query_weights:
                variant_filtered = [
                    c for c in best_candidates
                    if any(w in normalize_text_for_search(c.name) for w in query_weights)
                ]
                if len(variant_filtered) == 1:
                    best_candidates = variant_filtered

            if len(best_candidates) == 1:
                # If query has un-matched descriptive tokens (e.g. brown, free, black, essential), mark ambiguous rather than silent match
                c_norm = normalize_text_for_search(best_candidates[0].name)
                c_tokens = set(c_norm.split())
                unmatched_q_tokens = [
                    t for t in q_tokens 
                    if t not in c_tokens and not any(t in ct for ct in c_tokens) and t not in WEIGHT_AND_CONTAINER_TOKENS
                ]
                if unmatched_q_tokens:
                    add_ambiguous(item, best_candidates)
                else:
                    add_match(best_candidates[0], item)
            elif len(best_candidates) > 1:
                add_ambiguous(item, best_candidates)
            else:
                unmatched_items.append(
                    UnmatchedVoiceItem(
                        queried_name=item.name,
                        quantity=item.quantity,
                        reason="Product not found in shop inventory",
                    )
                )
        else:
            unmatched_items.append(
                UnmatchedVoiceItem(
                    queried_name=item.name,
                    quantity=item.quantity,
                    reason="Product not found in shop inventory",
                )
            )

    # Bill = sum of the rounded lines (Decimal); no GST is calculated for voice bills
    subtotal_d = bill_total(to_decimal(m.total_price) for m in matched_items)
    tax_d = Decimal("0")
    subtotal, tax, total = to_number(subtotal_d), to_number(tax_d), to_number(round_currency(subtotal_d + tax_d))

    return matched_items, ambiguous_items, unmatched_items, subtotal, tax, total
