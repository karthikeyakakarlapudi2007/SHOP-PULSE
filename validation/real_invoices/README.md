# Real invoice photographs for validation

This folder is where real grocery invoice photographs are placed to measure ShopPulse's invoice
scanner on real-world input. **It is empty on purpose:** no real photographs with verified
provenance were available when the harness was prepared, so no real-world accuracy has been
measured yet. Results from simulated photos, scans or repository fixtures are reported separately
and are not real-world evidence.

## 1. What to photograph (aim for 20–30 invoices)

Use real supplier invoices from different grocery wholesalers, photographed with ordinary phones
the way a shop owner would. Cover as many of these as you can (one photo can cover several):

| Area | Cases to include | `conditions` tags |
|---|---|---|
| Quality | clear · low light · overexposed · shadow across the page · blurry · small text (taken from far) · folded or crumpled · faded print | `clear` `low_light` `overexposed` `shadow` `blurry` `small_text` `folded` `crumpled` `faded` |
| Orientation | upright · turned 90° · upside down · turned 270° · slightly tilted | `rotated_0` `rotated_90` `rotated_180` `rotated_270` `tilted` |
| Perspective | straight from above · angled · strong perspective · curved/uneven paper | `straight` `angled` `perspective` `curved` |
| Invoices | different shops, layouts, table styles, fonts and paper sizes (A4, A5, thermal roll, dot-matrix) · multi-page invoices · handwritten entries | `multi_page` `thermal` `dot_matrix` `handwritten` |
| Language | English invoices; if available, invoices with Telugu, Hindi, Tamil, Kannada or other Indian-script text | set `language` (`en`, `te`, `hi`, ...) |

Suggested minimum: 6 clear, 3 low light, 2 overexposed, 3 shadow, 3 blurry, 2 small text,
2 folded/crumpled, 2 faded, 2 each of 90°/180°/270°, 3 tilted, 3 angled, 2 multi-page.

Capture rules: original camera files (JPG or HEIC straight from the phone; do not edit, crop,
rotate, filter or re-save; do not send through WhatsApp, which recompresses). Several pages of one
invoice are listed in order in `files`.

## 2. Privacy

Before adding a photo, cover or blur personal details that are not needed for testing: customer
phone numbers, addresses, GSTIN/PAN, bank details, signatures and QR codes (a sticky note over
them before taking the photo works best). Supplier names and product lines are needed. Photos and
`manifest.json` are git-ignored here (see `.gitignore`); do not commit unanonymized invoices.

## 3. Ground truth (`manifest.json`)

Copy `manifest.template.json` to `manifest.json` and add one case per invoice. Type every value
**exactly as printed**:

* `header`: supplier name, invoice number and invoice date as printed; `null` if the invoice does
  not print it. Never fill in a value that is not on the paper.
* `items`: one entry per printed line, in order. `quantity` is the billed quantity (not the pack
  size in the product name: "Atta 10kg" bought 5 times has quantity 5). `unit` exactly as printed
  ("bag", "pkt", "KGS"); no conversions. `purchase_price` is the rate column; `mrp` only if an MRP
  column is printed (never copy the rate into MRP); `discount` and `tax_amount` only if printed;
  `printed_amount` is the line amount. Keep decimals exactly (58.75, 0.85, 2.5).
* Missing values stay `null`. If a printed value cannot be read with certainty even by eye, list the
  field in `ambiguous` so it is excluded from scoring, and describe it in `notes`.
* `ground_truth_text` (optional): the full text of the invoice typed line by line, for CER/WER.
* `provenance.source`: `real_photo` for phone photographs, `scan` for scanner images,
  `screenshot` for digital invoices. Only `real_photo` cases count as real-world results.

## 4. Run

```bash
cd backend
.venv/bin/python tests/real_world_validation.py --photos ../validation/real_invoices --check
.venv/bin/python tests/real_world_validation.py --photos ../validation/real_invoices \
    --md ../validation/real_invoices/results/report.md --json ../validation/real_invoices/results/report.json
```

`--check` validates the manifest and that every photo can be read, without running OCR. The full
run compares each original photo with the prepared page through the same existing extraction
pipeline and reports, per provenance category: fully and partially correct lines; product name,
quantity, unit, rate, MRP and amount accuracy; supplier, invoice number and date; values invented
for fields the invoice does not print; decimal-point corruptions (58.75 read as 58575 or 5875);
CER/WER (with a transcript); critical-token recall; preparation time per page; PDF size; memory;
cases where preparation did worse than the original photo; and results per condition.
