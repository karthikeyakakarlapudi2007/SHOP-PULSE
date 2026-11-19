import re
from typing import List, Tuple, Optional, Union
from pydantic import BaseModel

class ExtractedItem(BaseModel):
    name: str
    quantity: Union[int, float] = 1
    # Registered unit id (kg, g, L, ml, pcs, packet, ...) when a unit was spoken; None when not spoken
    unit: Optional[str] = None
    # Spoken line total ("3 tea for 100 rupees" -> 100)
    spoken_price: Optional[float] = None
    # Spoken price per unit ("100 rupees each", "60 rupees per kg"); price_unit is the unit it is per
    # (None for "each": per spoken unit)
    spoken_unit_price: Optional[float] = None
    price_unit: Optional[str] = None

# Comprehensive mapping of spoken numbers to integer digits across English and Indian languages
NUMBER_WORDS = {
    # English
    "zero": 0,
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty five": 25,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "hundred": 100,
    # Fractions & Spoken quantities
    "half": 0.5,
    "quarter": 0.25,
    "aadha": 0.5,
    "adha": 0.5,
    "ara": 0.5,
    "paavu": 0.25,
    "pao": 0.25,
    "pav": 0.25,
    "dedh": 1.5,
    "dhai": 2.5,
    "आधा": 0.5,
    "अर": 0.5,
    "పావు": 0.25,
    "అర": 0.5,
    "அரை": 0.5,
    "கால்": 0.25,
    "ಅರ್ಧ": 0.5,
    "ಕಾಲು": 0.25,
    "അര": 0.5,
    "കാൽ": 0.25,
    "अर्धा": 0.5,
    "আধা": 0.5,
    "અડધો": 0.5,
    "ਅੱਧਾ": 0.5,
    "ଅଧା": 0.5,
    # Hindi / Hinglish transliterations
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "chaar": 4,
    "paanch": 5,
    "panch": 5,
    "che": 6,
    "chhe": 6,
    "saat": 7,
    "aath": 8,
    "nau": 9,
    "das": 10,
    "dus": 10,
    "gyarah": 11,
    "barah": 12,
    "pandrah": 15,
    "bees": 20,
    "pachees": 25,
    "tees": 30,
    "chalis": 40,
    "pachaas": 50,
    "sau": 100,
    # Telugu transliterations
    "okati": 1,
    "rendu": 2,
    "moodu": 3,
    "naalugu": 4,
    "aidu": 5,
    "aaru": 6,
    "yedu": 7,
    "enimidi": 8,
    "tommidi": 9,
    "padi": 10,
    # Tamil transliterations
    "onnu": 1,
    "ondru": 1,
    "moonu": 3,
    "naalu": 4,
    "anju": 5,
    "yezhu": 7,
    "ettu": 8,
    "onbadhu": 9,
    "patthu": 10,
    # Devanagari numerals
    "एक": 1,
    "दो": 2,
    "तीन": 3,
    "चार": 4,
    "पांच": 5,
    "पाँच": 5,
    "छह": 6,
    "सात": 7,
    "आठ": 8,
    "नौ": 9,
    "दस": 10,
    "बारह": 12,
    "पंद्रह": 15,
    "बीस": 20,
    "पचास": 50,
    "सौ": 100,
    # Telugu script numerals & words
    "ఒకటి": 1,
    "ఒక": 1,
    "రెండు": 2,
    "మూడు": 3,
    "నాలుగు": 4,
    "ఐదు": 5,
    "ఆరు": 6,
    "ఏడు": 7,
    "ఎనిమిది": 8,
    "తొమ్మిది": 9,
    "పది": 10,
    "ఇరవై": 20,
    "ముప్పై": 30,
    "యాభై": 50,
    "నూరు": 100,
    "వంద": 100,
    # Tamil script
    "ஒன்று": 1,
    "ஒரு": 1,
    "இரண்டு": 2,
    "ரெண்டு": 2,
    "மூன்று": 3,
    "நான்கு": 4,
    "ஐந்து": 5,
    "பத்து": 10,
    # Kannada script
    "ಒಂದು": 1,
    "ಎರಡು": 2,
    "ಮೂರು": 3,
    "ನಾಲ್ಕು": 4,
    "ಐದು": 5,
    "ಹತ್ತು": 10,
    # Bengali script
    "এক": 1,
    "দুই": 2,
    "তিন": 3,
    "চার": 4,
    "পাঁচ": 5,
    "দশ": 10,
}

# Unit qualifiers that follow or precede numbers
PACKAGING_UNITS_REGEX = r"\b(?:కిలోల?|కేజీల?|లీటర్ల?|ప్యాకెట్ల?|బాటిల్|సంచులు|किलो|लीटर|पैकेट|बोतल|पॉकेट|கிலோ|லிட்டர்|பாக்கெட்|ಕಿಲೋ|ಲೀಟರ್|ಕിലോ|ലിറ്റർ|কেজি|packets?|pkts?|pouches?|pouch|boxes?|box|dabba|dappe|pieces?|pcs?|pc|bottles?|btls?|cans?|bags?|trays?|bori|basta|units?|liters?|ltrs?|ltr|kg|kilo|grams?|gms?)\b(?:\s+of\b)?"

UNIT_STRING_LIST = [
    "kg", "kgs", "kilo", "kilos", "gram", "grams", "g", "gm", "gms",
    "liter", "liters", "litre", "litres", "l", "ltr", "ltrs", "ml",
    "packet", "packets", "pack", "packs", "pkt", "pkts", "pouch", "pouches",
    "piece", "pieces", "pc", "pcs", "unit", "units",
    "box", "boxes", "bottle", "bottles", "btl", "btls", "bag", "bags",
    "కిలో", "కిలోలు", "కిలోల", "కేజీ", "కేజీలు", "కేజీల", "లీటర్", "లీటర్లు", "లీటర్ల", "ప్యాకెట్", "ప్యాకెట్లు", "ప్యాకెట్ల",
    "किलो", "किलों", "लीटर", "लीटरों", "पैकेट", "पैकेटों", "बोतल",
    "கிலோ", "லிட்டர்", "பாக்கெட்",
    "ಕಿಲೋ", "ಲೀಟರ್", "ಪ್ಯಾಕೆಟ್",
    "കിലോ", "ലിറ്റർ", "പാക്കറ്റ്"
]

# Spoken unit words in regional scripts / colloquial English, mapped to canonical registry unit ids.
# Language vocabulary only: the units themselves (families, factors, fraction rules) come from the registry.
REGIONAL_UNIT_IDS = {
    **{w: "kg" for w in ["కిలో", "కిలోలు", "కిలోల", "కేజీ", "కేజీలు", "కేజీల", "किलो", "किलों", "கிலோ", "ಕಿಲೋ", "കിലോ", "কেজি"]},
    **{w: "L" for w in ["లీటర్", "లీటర్లు", "లీటర్ల", "लीटर", "लीटरों", "லிட்டர்", "ಲೀಟರ್", "ലിറ്റർ"]},
    **{w: "packet" for w in ["ప్యాకెట్", "ప్యాకెట్లు", "ప్యాకెట్ల", "पैकेट", "पैकेटों", "पॉकेट", "பாக்கெட்", "ಪ್ಯಾಕೆಟ್", "പാക്കറ്റ്"]},
    **{w: "bottle" for w in ["बोतल", "బాటిల్"]},
    "dabba": "box", "dappe": "box", "సంచులు": "bag", "basta": "bag",
}


def canonical_voice_unit(word: Optional[str]) -> Optional[str]:
    """Registry unit id for a spoken unit word, or None when it is not a unit ("unit", "each", unknown).

    An unrecognised word is never turned into pcs: the product's own unit applies instead."""
    if not word or not word.strip():
        return None
    from services.unit_registry import try_normalize_unit  # local import keeps the parser import-light
    w = word.strip()
    return try_normalize_unit(w.lower()) or REGIONAL_UNIT_IDS.get(w.lower()) or REGIONAL_UNIT_IDS.get(w)


SORTED_UNITS_PATTERN = "|".join(re.escape(u) for u in sorted(UNIT_STRING_LIST, key=lambda x: -len(x)))

CURRENCY_REGEX = r"(?:రూపాయలు|రూ|రూ\.|రూపాయ|ర రూపాయలు|रुपये|रुपया|रु|रु\.|रू|रूपए|ரூபாய்|ரூ|ರೂಪಾಯಿ|രൂപ|টাকা|રૂપિયા|ਰੁਪਏ|ਟଙ୍କਾ|টকা|rupees?|rs|rs\.|inr)"

# Conversational fillers at start or end of phrases
CONVERSATIONAL_FILLERS = [
    r"^(?:please\s+)?(?:give\s+me|give\s+us|i\s+want|we\s+need|add|bill|put|take|pack|bhejo|dena|daal\s+do|likho|chahiye|ivvandi|kaavali)\s+",
    r"\s+(?:chahiye|dena|daal\s+do|likho|bhejo|ivvandi|kaavali|please)$",
    r"(?:kripya|bhai|bhaiya|ji|andi|ayya)",
]

def normalize_digits_and_numbers(text: str) -> str:
    """
    Replaces spoken number words, Devanagari digits, and fractions with numeric characters.
    """
    s = text.strip()

    # Convert Indic script digits to standard 0-9
    devanagari_digits = str.maketrans("०१२३४५६७८९", "0123456789")
    telugu_digits = str.maketrans("౦౧౨౩౪౫౬౭౮౯", "0123456789")
    bengali_digits = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
    s = s.translate(devanagari_digits).translate(telugu_digits).translate(bengali_digits)

    s = f" {s} "

    # Regional compound numbers & prices
    s = re.sub(r"(?<=\s)(?:నూట\s+యాభై|ఒక\s+వంద\s+యాభై)(?=\s)", " 150 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<=\s)(?:నూట\s+ఇరవై|వంద\s+ఇరవై)(?=\s)", " 120 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<=\s)(?:एक\s+सौ\s+बीस)(?=\s)", " 120 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<=\s)(?:one\s+hundred\s+twenty)(?=\s)", " 120 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?<=\s)(?:एक\s+सौ\s+पचास)(?=\s)", " 150 ", s, flags=re.IGNORECASE)

    # Fractions & composites
    s = re.sub(r"\b(?:one\s+and\s+a\s+half|one\s+and\s+half|1\s+and\s+a\s+half|1\s+and\s+half)\b", " 1.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:two\s+and\s+a\s+half|two\s+and\s+half|2\s+and\s+a\s+half|2\s+and\s+half)\b", " 2.5 ", s, flags=re.IGNORECASE)
    # Fractions of a unit keep the unit (it decides the stock quantity, e.g. half kg of a g product)
    s = re.sub(r"\b(?:half\s+a\s+kg|half\s+kg|half\s+kilo)\b", " 0.5 kg ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:half\s+a\s+(?:liter|litre)|half\s+liter|half\s+litre|half\s+ltr)\b", " 0.5 liter ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:quarter\s+kg|quarter\s+kilo)\b", " 0.25 kg ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:quarter\s+liter|quarter\s+litre)\b", " 0.25 liter ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:1\/2|½)\b", " 0.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:1\/4|¼)\b", " 0.25 ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:3\/4|¾)\b", " 0.75 ", s, flags=re.IGNORECASE)

    # Telugu spoken fractions
    s = re.sub(r"(?:ఒకటిన్నర)", " 1.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:రెండున్నర)", " 2.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:అర\s+కిలో|అర\s+కేజీ)", " 0.5 కిలో ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:అర\s+లీటర్)", " 0.5 లీటర్ ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:పావు\s+కిలో|పావు\s+కేజీ)", " 0.25 కిలో ", s, flags=re.IGNORECASE)

    # Hindi spoken fractions
    s = re.sub(r"(?:डेढ़\s+किलो)", " 1.5 किलो ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:डेढ़|डेढ)", " 1.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:ढाई\s+किलो)", " 2.5 किलो ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:ढाई)", " 2.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:आधा\s+किलो)", " 0.5 किलो ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:आधा\s+लीटर)", " 0.5 लीटर ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:पाव\s+किलो)", " 0.25 किलो ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:पाव)", " 0.25 ", s, flags=re.IGNORECASE)

    # Composite dozen expressions
    s = re.sub(r"\b(?:half\s+dozen|aadha\s+dozen|aadha\s+darjan|adha\s+dozen)\b", " 6 ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:one\s+dozen|1\s+dozen|dozen|darjan)\b", " 12 ", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:two\s+dozen|2\s+dozen)\b", " 24 ", s, flags=re.IGNORECASE)

    # Word-boundary replacement for single number words
    for word, val in sorted(NUMBER_WORDS.items(), key=lambda x: -len(x[0])):
        if word.isascii():
            pattern = rf"\b{re.escape(word)}\b"
        else:
            pattern = rf"(?<![ऀ-ൿ\w]){re.escape(word)}(?![ऀ-ൿ\w])"
        s = re.sub(pattern, f" {val} ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:two\s+and\s+a\s+half|two\s+and\s+half|2\s+and\s+a\s+half|2\s+and\s+half)", " 2.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:half\s+a\s+kg|half\s+kg|half\s+kilo|half\s+liter|half\s+litre|half\s+ltr)", " 0.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:quarter\s+kg|quarter\s+kilo|quarter\s+liter)", " 0.25 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:1\/2|½)", " 0.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:1\/4|¼)", " 0.25 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:3\/4|¾)", " 0.75 ", s, flags=re.IGNORECASE)

    # Telugu spoken fractions
    s = re.sub(r"(?:ఒకటిన్నర)", " 1.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:రెండున్నర)", " 2.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:అర\s+కిలో|అర\s+కేజీ|అర\s+లీటర్)", " 0.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:పావు\s+కిలో|పావు\s+కేజీ)", " 0.25 ", s, flags=re.IGNORECASE)

    # Hindi spoken fractions
    s = re.sub(r"(?:डेढ़\s+किलो|डेढ़|डेढ)", " 1.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:ढाई\s+किलो|ढाई)", " 2.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:आधा\s+किलो|आधा\s+लीटर)", " 0.5 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:पाव\s+किलो|पाव)", " 0.25 ", s, flags=re.IGNORECASE)

    # Composite dozen expressions
    s = re.sub(r"(?:half\s+dozen|aadha\s+dozen|aadha\s+darjan|adha\s+dozen)", " 6 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:one\s+dozen|1\s+dozen|dozen|darjan)", " 12 ", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:two\s+dozen|2\s+dozen)", " 24 ", s, flags=re.IGNORECASE)

    # Word-boundary replacement for single number words
    for word, val in sorted(NUMBER_WORDS.items(), key=lambda x: -len(x[0])):
        if word.isascii():
            pattern = r"" + re.escape(word) + r""
        else:
            pattern = rf"(?<=\s){re.escape(word)}(?=\s)"
        s = re.sub(pattern, f" {val} ", s, flags=re.IGNORECASE)

    return s.strip()

# Price connector words left in the product text once the price itself is removed ("tea for", "soap at")
_PRICE_CONNECTORS = r"(?:for|at|@|each|apiece|rate|ka|ki|ke)"


def _strip_price_connectors(text: str) -> str:
    text = re.sub(r"\b(?:each|apiece)\b", " ", text, flags=re.IGNORECASE)
    prev = None
    while prev != text:
        prev = text
        text = re.sub(rf"\s+{_PRICE_CONNECTORS}\s*$", "", text.strip(), flags=re.IGNORECASE)
    return text.strip()


def _trailing_unit(text: str) -> Optional[str]:
    """Registry unit id of a count / package word ending the product text ("tea packets" -> packet).

    Measure abbreviations are not taken from the end of a name ("Parle G" is a brand, not grams)."""
    m = re.search(rf"(?:^|\s)({SORTED_UNITS_PATTERN})$", _strip_price_connectors(text), flags=re.IGNORECASE)
    unit = canonical_voice_unit(m.group(1)) if m else None
    if unit is None:
        return None
    from services.unit_registry import FAMILIES, UNITS
    return None if FAMILIES[UNITS[unit].family].kind == "measure" else unit


def _extract_price(s: str) -> Tuple[str, Optional[float], Optional[float], Optional[str]]:
    """Remove a spoken price from the clause.

    Returns (remaining text, line total, unit price, unit the price is per). "100 rupees each" or
    "45 rupees per kg" is a unit price (never taken as the line total); "100 rupees" or "for 100" is the
    line total. Nothing is guessed when no price is spoken."""
    cur = CURRENCY_REGEX
    per = rf"(?:each|apiece|a\s+piece|per\s+(?:piece|item|({SORTED_UNITS_PATTERN})))(?![\wऀ-ൿ])"
    unit_price = re.search(
        rf"(?:(?:@|\bat)\s*)?(?:(?:{cur})\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:{cur})?)\s*{per}",
        s, flags=re.IGNORECASE)
    if unit_price:
        value = float(unit_price.group(1) or unit_price.group(2))
        price_unit = canonical_voice_unit(unit_price.group(3)) if unit_price.group(3) else None
        rest = (s[:unit_price.start()] + " " + s[unit_price.end():]).strip()
        return rest, None, value, price_unit
    total = re.search(rf"(?:{cur})\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:{cur})", s, flags=re.IGNORECASE)
    if total:
        rest = (s[:total.start()] + " " + s[total.end():]).strip()
        return rest, float(total.group(1) or total.group(2)), None, None
    # "3 soap for 100": a trailing "for <amount>" is the line total when another number gives the quantity
    for_total = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*$", s, flags=re.IGNORECASE)
    if for_total and re.search(r"\d", s[:for_total.start()]):
        return s[:for_total.start()].strip(), float(for_total.group(1)), None, None
    return s, None, None, None


def clean_product_name(raw_name: str) -> str:
    """
    Cleans extracted product text: removes leading unit qualifiers, conversational fillers,
    and trailing plurals while strictly preserving package weights/sizes (like 1kg, 500g).
    """
    name = _strip_price_connectors(raw_name.strip())
    # Remove leading conversational fillers
    for pattern in CONVERSATIONAL_FILLERS:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()

    # Remove leading packaging units (e.g. "kg rice" -> "rice", "packets of salt" -> "salt")
    name = re.sub(r"^(?:" + PACKAGING_UNITS_REGEX + r")\s*", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(r"^\s*of\s+", "", name, flags=re.IGNORECASE).strip()

    # Remove trailing isolated packaging unit if not part of a size like 1kg
    name = re.sub(r"\s+(?:" + PACKAGING_UNITS_REGEX + r")$", "", name, flags=re.IGNORECASE).strip()

    # Normalize whitespace
    name = re.sub(r"\s+", " ", name).strip(" ,.-;")

    # Remove simple plural 's' at the end of word if appropriate
    words = name.split()
    cleaned_words = []
    for w in words:
        lower_w = w.lower()
        if lower_w in ["salts", "attas", "milks", "breads", "butters", "rices", "sugars", "oils", "biscuits"]:
            cleaned_words.append(w[:-1])
        else:
            cleaned_words.append(w)
    name = " ".join(cleaned_words)

    # Remove spoken currency terms and price amounts
    name = re.sub(rf"\d+(?:\.\d+)?\s*{CURRENCY_REGEX}", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(rf"{CURRENCY_REGEX}\s*\d+(?:\.\d+)?", "", name, flags=re.IGNORECASE).strip()
    name = re.sub(rf"{CURRENCY_REGEX}", "", name, flags=re.IGNORECASE).strip()

    # Standardize common spelling/brand aliases for Indian FMCG
    name_lower = name.lower()
    if name_lower in ["parle g", "parle-g", "parleg", "పార్లే జి", "పార్లే జీ", "पारले जी", "பார்லே ஜி"]:
        name = "Parle-G"
    elif name_lower in ["tata salt", "tata namak", "టాటా ఉప్పు", "టాటా సాల్ట్", "टाटा नमक", "टाटा साल्ट", "டாடா உப்பு", "டாடா சால்ట్", "ಟಾಟಾ ಉಪ್ಪು"]:
        name = "Tata Salt"
    elif name_lower in ["aashirvaad atta", "ashirvad atta", "aashirwad atta", "ఆశీర్వాద్ గోధుమ పిండి", "ఆశీర్వాద్ పిండి", "ఆశీర్వాద్ ఆటా", "आशीर्वाद आटा"]:
        name = "Aashirvaad Atta"

    return name.strip()

def extract_items_from_transcript(transcript: str) -> List[ExtractedItem]:
    """
    Parses natural language transcript into structured list of ExtractedItem.
    Supports continuous multi-items, forward & reverse order, spoken prices, and fractions.
    """
    if not transcript or not transcript.strip():
        return []

    normalized = normalize_digits_and_numbers(transcript)

    # Split into item clauses by common spoken sentence connectors
    delimiters = r"[,;\n\+]|\b(?:and|aur|plus|mariyu|matrum|evam|tatha)\b|&"
    raw_segments = [s.strip() for s in re.split(delimiters, normalized, flags=re.IGNORECASE) if s.strip()]

    items: List[ExtractedItem] = []

    for raw_seg in raw_segments:
        s = raw_seg.strip()
        for pattern in CONVERSATIONAL_FILLERS:
            s = re.sub(pattern, "", s, flags=re.IGNORECASE).strip()

        if not s:
            continue

        while len(s) > 0:
            s = s.strip()
            if not s:
                break

            # Extract a spoken price if present: a line total, or a unit price ("each", "per kg")
            s, extracted_price, unit_price, price_unit = _extract_price(s)
            price_fields = dict(spoken_price=extracted_price, spoken_unit_price=unit_price, price_unit=price_unit)

            # Pattern 1: Leading quantity (e.g. "2 kg rice", "2 Tata Salt", "2 Tata Salt 1kg", "0.5 kg sugar")
            lead_regex = re.compile(
                rf"^(\d+(?:\.\d+)?)\s*(?:({SORTED_UNITS_PATTERN})(?:\s+of)?)?\s+(.+?)(?=(?:\s+\d+(?:\.\d+)?(?:\s+(?:{SORTED_UNITS_PATTERN}))?\s+[a-zA-Zऀ-ൿ])|$)",
                flags=re.IGNORECASE
            )
            lead_match = lead_regex.match(s)

            if lead_match:
                raw_qty = float(lead_match.group(1))
                qty_val = int(raw_qty) if raw_qty.is_integer() else raw_qty
                # "2 kg rice" (unit before the name) or "3 tea packets" (unit after the name)
                unit_id = canonical_voice_unit(lead_match.group(2)) or _trailing_unit(lead_match.group(3))
                prod_text = clean_product_name(lead_match.group(3))

                if prod_text:
                    items.append(ExtractedItem(
                        name=prod_text,
                        quantity=qty_val if qty_val > 0 else 1,
                        unit=unit_id,
                        **price_fields,
                    ))

                s = s[lead_match.end():].strip()
                continue

            # Pattern 2: Trailing quantity (e.g. "Rice 2 kg", "Sugar 1 kg", "Tata Salt 2 packets", "Parle-G 3")
            trail_regex = re.compile(
                rf"^([a-zA-Zऀ-ൿ0-9\s\-\(\)]+?)\s+(\d+(?:\.\d+)?)(?:\s+({SORTED_UNITS_PATTERN}))?(?=(?:\s+\d+)|\s+[a-zA-Zऀ-ൿ].*?\s+\d+|$)",
                flags=re.IGNORECASE
            )
            trail_match = trail_regex.match(s)

            if trail_match:
                prod_text = clean_product_name(trail_match.group(1))
                raw_qty = float(trail_match.group(2))
                qty_val = int(raw_qty) if raw_qty.is_integer() else raw_qty
                unit_id = canonical_voice_unit(trail_match.group(3))

                if prod_text:
                    items.append(ExtractedItem(
                        name=prod_text,
                        quantity=qty_val if qty_val > 0 else 1,
                        unit=unit_id,
                        **price_fields,
                    ))

                s = s[trail_match.end():].strip()
                continue

            # Pattern 3: Fallback single item without explicit number (e.g. "Tata Salt", "Aashirvaad Atta")
            prod_text = clean_product_name(s)
            if prod_text:
                items.append(ExtractedItem(
                    name=prod_text,
                    quantity=1,
                    unit=None,
                    **price_fields,
                ))
            break

    return items
