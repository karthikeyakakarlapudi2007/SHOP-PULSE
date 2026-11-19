# Phase 4 – Workstream 1: Canonical unit registry

Status: implemented, not committed. Approved decisions D-1 (fractional units) and D-4 (product-specific conversions) apply.
Markers: [C] confirmed by code or by running it, [R] recommendation, [D] decision needed.

## 1. Architecture

**Before [C]:** four separate unit vocabularies, with no shared conversion or compatibility rules.

| Vocabulary | Role |
|---|---|
| OCR `CANONICAL_UNITS` (72 aliases → 21 codes) | invoice unit normalisation |
| `product_matching._UNIT_ALIASES` / `_TO_BASE` (kg, g, l, ml) | pack sizes in product names |
| Frontend voice `CanonicalUnit` and `UNIT_NORMALIZATION_MAP` | spoken units (also Telugu, Hindi, Tamil, …) |
| `products.unit` | free text |

**After:**

| Component | Role |
|---|---|
| `backend/services/unit_registry.py` | **the single source of truth.** It took over every OCR alias and code, and added families, base units, factors and fraction rules |
| OCR normaliser | `CANONICAL_UNITS` is now *derived* from the registry (same name, same alias → code mapping) |
| Product matching | resolves pack-size units through the registry |
| `GET /api/v1/units` | serialises the registry; the frontend keeps no unit list of its own |

Why the new module isn't a "fifth list":
- the OCR table *moved into* it, and the OCR module now reads from it;
- it lives outside `grocery_ocr/` because products, sales, purchases and voice will all use it.

## 2. Registry structure

```
UnitFamily(id, label, kind: measure | count | package, base_unit)
UnitDefinition(id, label, family, factor (base units per unit, whole number), allows_fraction,
               ocr_code (legacy OCR code, kept for compatibility), aliases)
```
- **Integrity checks at import:** every alias must be normalised and must belong to exactly one unit, so an ambiguous alias stops the app from starting. Every family's base unit must be a factor-1 member.

| Family | Kind | Base | Units (factor to base) | Fractional |
|---|---|---|---|---|
| mass | measure | g | kg (1000), g (1), qtl (100000), ton (1000000) | kg, g **yes**; qtl, ton no [D] |
| volume | measure | ml | L (1000), ml (1) | **yes** |
| count | count | pcs | pcs (1), nos (1), dozen (12) | no |
| packet, box, bottle, bag, bora, tin, can, jar, pouch, carton, case, set | package (one family each) | the unit itself | itself (1) | no |

- **`qtl` and `ton`:** these mass units existed in the OCR table. The approved rule (D-1) names only kg, g, L and ml as fractional, so they are whole-number. **[D]** Approve fractional quintal and tonne if needed.
- **`nos`:** "numbers" stays a separate count unit (factor 1 to pcs) so OCR keeps producing its `NOS` code.

## 3. Aliases (matched after removing punctuation and spaces, case-insensitive)

| Unit | Aliases |
|---|---|
| kg | kg, kgs, kes, kilo, kilos, kilogram, kilograms |
| g | g, gm, gms, gr, gram, grams |
| qtl | qtl, quintal, quintals |
| ton | ton, tons, tonne, tonnes |
| L | l, lt, ltr, ltrs, litre, litres, liter, liters |
| ml | ml, mls, millilitre, millilitres, milliliter, milliliters |
| pcs | pcs, pc, piece, pieces |
| nos | nos, no, num |
| dozen | doz, dz, dozen, dozens |
| packet | pkt, pkts, pack, packs, packet, packets |
| box | box, boxes, bx |
| bottle | bottle, bottles, btl, btls, pet, pets |
| bag / bora / tin / can / jar / pouch / carton / case / set | bag(s); bor, bora, bori, boras; tin(s); can(s); jar(s); pouch(es); ctn, carton(s); case(s); set(s) |

- **No alias was removed [C]:** all 72 former OCR aliases map to the same OCR code (regression test).
- **Added:** `gr` (from product matching), millilitre / milliliter (singular and plural), `dozens`, `quintals`, `tons`, `tonnes`.
- **Unknown units:** `normalize_unit` raises `UnknownUnitError`, and the frontend returns `null`. They are **never** turned into pcs. The OCR normaliser keeps its previous behaviour for unknown units: verbatim text, `is_recognized=False`.

## 4. Helpers (`services/unit_registry.py`)

| Function | Behaviour |
|---|---|
| `normalize_unit(raw)` / `try_normalize_unit(raw)` | id, or `UnknownUnitError` / `None` |
| `get_unit`, `get_unit_family`, `get_base_unit` | registry lookups |
| `are_units_compatible(a, b)` | same family |
| `convert_quantity(q, from, to, product_conversions=None)` | exact `Decimal`. Within a family it uses the factors; across families, only an explicitly supplied product conversion. Raises `IncompatibleUnitsError`, or `InexactConversionError` (e.g. 10 pcs → dozen = 0.8333…); **never rounds** |
| `validate_quantity_unit(q, unit, allow_zero=False)` | > 0 (or ≥ 0); kg, g, L, ml up to 3 decimals; every other unit whole |
| `ProductUnitConversion.create(from, to, factor, product_id=None)` | validated product-specific conversion (see §5) |

- **Float input:** floats are read through their shortest representation, so `1.1 kg → 1100 g`, not `1100.0000000000002`.
- **No money:** no monetary arithmetic is involved.

**Examples (all tested):**
- 2.5 kg → 2500 g; 2500 g → 2.5 kg; 0.75 L → 750 ml; 1 dozen → 12 pcs; 30 pcs → 2.5 dozen.
- kg → L fails; packet → kg fails ("needs a product-specific conversion").

## 5. Product-specific conversions (D-4)
- **Rule:** `ProductUnitConversion` only starts from a **package** unit, must target another family, and needs a factor valid for the target unit (1 box = 24 pcs is whole; 1 packet = 0.5 kg is fine; 1 box = 2.5 pcs is refused). Conflicting conversions are refused.
- **Applied only when passed in:** e.g. 2 box → 48 pcs → 4 dozen, and reverse. Without it, box → pcs fails. No global package sizes exist.
- **Not persisted.** Storing per-product conversions needs a new table (`product_unit_conversions`, proposed in `DATABASE_MIGRATION_PROPOSAL.md` §3). **[D] That needs a separate migration approval,** so this workstream has no storage and no API to configure conversions.

## 6. API contract: `GET /api/v1/units`
- **Authentication:** required (`deps.get_current_user`), like the product routes. Anonymous requests get 401.
- **Read-only:** no database writes. POST, PUT, PATCH and DELETE return 405.
- **Body:** `registry_payload()`, generated from the registry; a test asserts equality.

```json
{
  "version": 1,
  "max_fraction_digits": 3,
  "families": [
    {"id": "mass", "label": "Mass", "kind": "measure", "base_unit": "g", "auto_convertible": true,
     "units": ["kg", "g", "qtl", "ton"]},
    {"id": "box", "label": "Box", "kind": "package", "base_unit": "box", "auto_convertible": false, "units": ["box"]}
  ],
  "units": [
    {"id": "kg", "label": "kg", "family": "mass", "kind": "measure", "base_unit": "g", "factor_to_base": 1000,
     "allows_fraction": true, "convertible": true, "compatible_units": ["kg", "g", "qtl", "ton"],
     "aliases": ["kes", "kg", "kgs", "kilo", "kilogram", "kilograms", "kilos"]},
    {"id": "box", "label": "box", "family": "box", "kind": "package", "base_unit": "box", "factor_to_base": 1,
     "allows_fraction": false, "convertible": false, "compatible_units": ["box"], "aliases": ["box", "boxes", "bx"]}
  ]
}
```
(Abbreviated; the full response has 15 families and 21 units.)

## 7. Frontend integration
- **API and lookups:**
  - `src/api/units.ts`: types and `unitsApi.getRegistry()`;
  - `src/utils/unitRegistry.ts`: `createUnitIndex(registry)` with normalize, get, areCompatible and allowsFraction. It's built only from the API data, uses the same normalisation as the backend, returns `null` for unknown units and has no fallback.
- **`src/hooks/useUnitRegistry.ts`:** loads once and shares the result. If the API is unavailable it reports `error` and returns no index; a later mount retries.
- **Product form (`ProductFormFields`, used by both add and edit):**
  - the unit field is **still free text** with the same default (`pkts`) and validation;
  - it now offers the registry units as browser suggestions (`<datalist>`);
  - without the registry there are simply no suggestions; nothing is substituted.
- **Voice parser:** its internal unit names (piece, packet, bottle, dozen, …) all resolve through the registry aliases, so no extra mapping list is needed.

## 8. Product matching with the registry (final verification)

**Only change:** product matching now resolves pack-size units through the registry. The pack-size pattern finds the same spellings as before; the only spelling it finds that the old table didn't know is **"kilos"**.

Old and new code compared on the same name pairs [C]:

| Pair | Old score | New score | Effect |
|---|---|---|---|
| Rice 25 kilos / Rice 25000 g | 0.565 | **1.0** | the same product is now recognised |
| Rice 25 kg / Rice 25000 g | 1.0 | 1.0 | unchanged |
| Rice 25 kg / Rice 25 g | 0.0 | 0.0 | different sizes never match |
| Rice 25 kg / Rice 25 packets | 0.456 | 0.456 | no match (packets aren't a pack size) |
| Atta 5 kilos / Atta 10 kilos | **0.922** (above the 0.88 match threshold) | **0.0** | old code could merge two sizes; now blocked |
| Rice 2.5 kilos / Rice 25 kilos | **0.976** | **0.0** | old code could merge two sizes; now blocked |
| Distinct brands or variants, same weight (any spelling) | no match | no match | unchanged (scores 0.80–0.81) |

- **Conclusion:** normalising "kilos" improves matching and closes two cases where the old code could merge different pack sizes. It doesn't merge distinct products.
- **Regression tests:** in `test_unit_registry.py`, built from generated combinations of made-up brands, product categories and sizes, not individual product names. They cover:
  - every spelling of the same size matches;
  - equivalent sizes match;
  - different sizes never match;
  - distinct brands and distinct items of one brand at the same weight never match;
  - packet counts aren't pack sizes;
  - the correct size is chosen from a catalogue.
- **Pre-existing limitation (unchanged):** the matcher deliberately treats words that differ by one letter as OCR slips, so brand names like "BrandA" and "BrandB" score as the same word. That's existing OCR tolerance, not caused by the registry.

## 9. Tests (executed 2026-11-19)

| Level | Test | Result |
|---|---|---|
| Unit | `backend/tests/test_unit_registry.py`: every unit, every alias, required aliases, unknown units, families, compatibility, exact and inexact conversions, fraction rules, product conversions, product-matching regression | **129 passed** (includes integration below) |
| Integration | all 72 former OCR aliases give the same codes; OCR keeps unknown units verbatim and not as PCS; product matching yields the same results ("25 kilos" now = 25000 g) | pass |
| Integration | API: 401 anonymous; 200 with body = registry; 405 for writes; frontend fixture equals the live registry | pass |
| Unit (frontend) | `src/tests/unitRegistry.test.ts`: normalisation, unknown units → null, compatibility, fractions, loader caching, API-down rejection and retry, product-form wiring | 7 passed |
| System (final run) | full backend **816 passed, 7 skipped, 0 failed**; full Vitest **111 passed (15 files)**, re-run after the `testIsolation` lint fix; TypeScript, lint (exit 0; no warnings in workstream 1 files) and build pass | pass |
| System | browser checks through the launcher: 25/25, 12/12, 6/6, 17/17, 18/18, **new `unit_registry_check` 16/16** (three consecutive runs) | pass |
| Regression | OCR dataset run (fixtures, synthetic, simulated) vs the last recorded run | **all extracted values identical**; only `status` differs in 23 cases, from the earlier approved status fix (`6da7393`) |
| Acceptance | 2.5 kg→2500 g; 2500 g→2.5 kg; 0.75 L→750 ml; 1 dozen→12 pcs; kg→L fails; packet→kg fails without configuration; unknown OCR units not pcs; products, invoices, sales and inventory flows unchanged | pass |

## 10. Known limitations and remaining integration (later workstreams)

| Item | Where | Workstream |
|---|---|---|
| OCR still outputs legacy codes lowercased (`pet`, `pkt`, `doz`, `nos`) as the line unit. Mapping them to registry ids (bottle, packet, dozen) changes stored product units, so it's left for the confirm flow | `services/invoice.py`, `InvoiceScanner.tsx` | 7 |
| A **missing** unit defaults to `pcs` at invoice confirm (`invoice.py` `item.unit or "pcs"`, frontend `unit \|\| 'pcs'`). It's a missing unit, not an unknown one, but it is still an assumption | invoice confirm | 2 / 7 |
| `products.unit` is free text, not validated against the registry; DB default `pcs` | product schema and model | 2 |
| Sales mapping hard-codes sale-line unit `'pcs'` | `salesService.ts` | 3 / 8 |
| Voice vocabularies: frontend `UNIT_NORMALIZATION_MAP` (multilingual spoken words) and backend `voice_parser.UNIT_STRING_LIST`. `normalizeSpokenUnit` falls back to `'piece'` but is not called anywhere [C] | Voice-to-Bill (not modified) | 7 |
| The pack-size regex in `product_matching` still lists unit spellings to find them in names (meaning comes from the registry) | product matching | 7 |
| Persisting product-specific conversions needs the `product_unit_conversions` table | migration | 5 [D] |
| Frontend text normalisation is ASCII-only; all aliases are ASCII today | `unitRegistry.ts` | – |
| Name matching treats words that differ by one letter as OCR slips (pre-existing) | product matching | – |
| Quintal and tonne are whole-number (approved for now) | registry | – |
| The registry endpoint needs a logged-in user (as the product routes do); the form shows no suggestions without one | API | – |
