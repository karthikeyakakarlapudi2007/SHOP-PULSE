# Voice-to-Bill – spoken prices, units and the cart (final integration)

No schema change or migration. API changes are additive response fields only.

## Problem found
The backend already kept a spoken price (`unit_price_exact`), but it was lost on the way to the sale:

1. `VoiceBillModal` handed the cart only `{product, quantity}`.
2. `Sales.tsx` priced cart lines, the bill total and the sale request from the catalogue (`product.sellingPrice`).
3. Choosing between ambiguous products used the catalogue price.

"3 tea packets for 100 rupees" therefore saved 3 × catalogue price.

Further gaps found in the same flow:
- the spoken unit was ignored: "500 g sugar" for a kg product became 500 kg;
- "100 rupees each" was taken as the line total;
- "half kg" lost its unit, and "for" stayed in the product name;
- the local instant parser rounded the unit price to 2 dp (₹100 / 3 → ₹99.99), and its unchecked preview stayed billable when the backend refused every line.

## Behaviour now
**Parser** (`backend/services/voice_parser.py`):
- "for 100 rupees" or "for 100" is the line total; "100 rupees each" or "45 rupees per kg" is a unit price;
- units are canonical registry ids;
- "half kg" / "आधा किलो" / "అర కిలో" keep kg;
- "tea packets" gives unit packet;
- a measure abbreviation at the end of a name is not a unit ("Parle G").

**Matcher** (`backend/services/inventory_matcher.py`):
- the quantity is converted into the product's stock unit by the registry (500 g → 0.5 kg, shown as "said 500 g");
- a count or package word for a count or package product means the product's own unit ("3 tea packets" of a pcs product);
- incompatible units (L for a kg product, kg for a pcs product) and fractions of whole-number units are listed as unmatched with a reason, never billed;
- a spoken total or unit price always wins over the catalogue (`price_source: spoken`), and quantity × `unit_price_exact` reproduces the total exactly;
- ambiguous items carry `spoken_price` and a ready line per candidate (`options`).

**Frontend:**
- the backend result is authoritative and replaces the instant preview even when it matched nothing; confirmation is disabled while the backend check runs;
- the modal hands each line's agreed unit price to the cart (`voiceLineToCartItem`), lets the user correct a line total ("Edited price"), and keeps the spoken price when an ambiguous product is chosen;
- cart lines carry `unitPrice` / `priceSource` (`src/utils/cartPricing.ts`):
  - line totals use exact BigInt arithmetic with the backend's half-up per-line rule, and the bill is the sum of the lines;
  - the sale request sends the line's price, so the displayed total equals the saved total;
  - a spoken-price line is never merged into or re-priced by a catalogue line of the same product;
- the local fallback parser keeps the exact spoken price and refuses a measure-unit mismatch instead of guessing.

## Verification
| Suite | Result |
|---|---|
| New `backend/tests/test_voice_pricing.py` | 22 passed (parser, matching, units, ambiguous options, API end to end: ₹100.00 saved, stock 20 → 17; 500 g → 9.5 kg) |
| New `src/tests/voicePricing.test.ts` | 10 passed |
| New browser check `voice_bill_price_check` (real Sales page + voice modal, desktop and Pixel 7) | 18/18 |
| Existing voice tests | 87 backend passed unchanged |

Frontend voice tests: three recognition tests sold "2 kg rice" against the mock 5 kg **bag** product (silently 2 bags). They now use a kg-stocked rice with the same recognition assertions, plus an assertion that the bag case is refused.

## Limitations
- Converting between package and count units (1 box = 12 pcs) needs a stored per-product conversion, which needs a migration. Voice treats such words as the product's own unit.
- Spoken-number coverage in the 12 languages is unchanged.
