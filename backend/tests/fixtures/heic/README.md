# HEIC/HEIF test fixtures

Generated from the synthetic invoice in `tests/doc_prep_dataset.py` (scale 0.6) with
`pillow-heif==1.8.1` (encoder; used only to create these files, not a runtime dependency).
The application decodes them with the decode-only `pi-heif` package.

| File | Stored pixels | Orientation metadata | Expected after loading |
|---|---|---|---|
| invoice_upright.heic | upright 744x1052 | none | upright 744x1052 |
| invoice_exif6.heic | sideways (rotated 90 CCW) | EXIF 6, written as an HEIF `irot` transform | upright 744x1052, rotated exactly once |
| invoice_sideways_noexif.heic | sideways 1052x744 | none | sideways; text-based orientation detection turns it upright |
| invoice_rgba.heic | upright, with alpha | none | alpha flattened onto white |
