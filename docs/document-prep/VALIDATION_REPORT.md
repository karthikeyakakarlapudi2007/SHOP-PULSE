# Invoice preparation & extraction: validation report

Scope: real-world validation of the invoice photo preparation layer, fixes for verified
extraction defects, HEIC support, mobile workflow validation and full regression.
Every number below comes from a run that was executed; nothing is estimated.

## 1. Data used, and what it is not

**No real photographs of invoices were available.** No photo set exists in the repository, no
device or camera is attached to this environment, and public receipt datasets were either blocked
by the network policy or outside this session's permitted GitHub scope. Therefore:

* `backend/tests/real_world_validation.py --photos DIR` is the harness for **real photos**:
  put phone photos plus a `manifest.json` (expected line items, optional transcript) in a folder
  and it reports the same before/after metrics. **This has not yet been run on real photos.**
* Results below use **simulated camera captures** of the repository's 10 invoice layouts
  (`tests/fixtures/ground_truth`, with known line items): pinhole perspective on textured
  backgrounds, uneven light, hard shadows, vignetting, focus/motion blur, light-dependent sensor
  noise, white-balance cast and JPEG. They are realistic but **simulated**, and are labelled so.

## 2. Results (existing OCR engine reads both sides)

### 2a. Simulated phone captures: full extraction (`real_world_validation.md`)
81 captures (10 layouts × 8 conditions + 1 two-page invoice), 416 line items. A line counts only
when product name, quantity, rate **and** amount are all correct.

| | Photo uploaded as today | Prepared page |
|---|---|---|
| Fully correct lines | **15 / 416** | **248 / 416** |
| Name / qty / rate / amount found | 38 / 21 / 22 / 27 | 277 / 255 / 259 / 267 |
| Cases with fewer correct lines than today | – | **0** |

| Condition | Correct lines today → prepared | Critical-token recall today → prepared |
|---|---|---|
| Sideways | 0 → 44 / 51 | 0.00 → 0.94 |
| Upside down | 0 → 46 / 51 | 0.00 → 0.96 |
| Low light | 0 → 32 / 51 | 0.00 → 0.84 |
| Shadow | 2 → 43 / 51 | 0.42 → 0.94 |
| Perspective | 3 → 32 / 51 | 0.28 → 0.84 |
| Tilted | 10 → 37 / 51 | 0.10 → 0.95 |
| Blurry | 0 → 6 / 51 | 0.00 → 0.31 |
| Small text (page fills half the frame, low resolution) | 0 → 0 / 51 | 0.00 → 0.26 |
| Two-page invoice (page 2 sideways) | 0 → 8 / 8 | 0.00 → 1.00 |

Blurry and small-text captures are mostly **not recoverable**; a retake was recommended for
18 of those 20 cases (2 missed: TC13 blurry, TC31 small text). A retake was also suggested for
2 of the other 61 cases (TC20 low light, which extracted 0/3, and TC20 perspective, which
extracted 3/3 – one unnecessary suggestion).

### 2b. Synthetic pages with exact transcripts: CER / WER (`ocr_comparison.md`)
17 cases. Examples (today → prepared): upside down CER 0.833 → 0.209; rotated 270° 0.831 → 0.129;
sideways + tilt 0.811 → 0.128; low light 1.000 → 0.128; perspective WER 0.409 → 0.109;
blurry critical tokens 0.452 → 0.839. Low resolution unchanged within noise (0.136 → 0.138).
Unrecoverable blur stays unreadable (retake requested).

### 2c. Repository fixtures: full extraction (`fixture_extraction_results.md`)
90 → 121 of 136 line items fully correct; no fixture worse.

### 2d. Change versus the interim run (before the low-light fix)
Low light improved on 7 layouts (+27 lines). One case got worse: TC26 small text 2 → 0 lines
(critical tokens still 1.00; table rows were split differently). Net 223 → 248.

## 3. Root causes and fixes

| # | Issue | Root cause (verified) | Fix | Where |
|---|---|---|---|---|
| 1 | Image-only PDFs read as "digital" with garbage words | `_extract_raw_pdf_stream_text` inflated **image** XObject streams and matched text-operator byte patterns in pixel data | Skip streams whose dictionary is `/Subtype /Image` and decoded streams that are not ≥ 90 % printable text | `grocery_ocr/processors/pdf_processor.py` (+22/−3, only protected file changed) |
| 2 | Supplier = `"voice No: INV-00427` | (a) `TextLineReconstructor` refuses to join words taller than max(1.6×median, 25 px), so large titles become one-word lines; (b) OCR clipped "In" from "Invoice No:", so the invoice-number regex missed it and the line became the fallback supplier | `extract_metadata`: rejoin consecutive one-word title lines, reject "… No:" field lines as supplier, accept `(in)voice No` (also recovers the invoice number). Reconstructor left unchanged because it drives table rows for every invoice | `services/invoice.py` |
| 3 | Rate 58575 instead of 58.75 | The OCR engine itself read `58.75` as `58575` (word confidence 66 vs ~95); the value was reported faithfully, but the API dropped all suggestions (`suggestions=[]`, `suggested_rate=None`) and the review table never showed issues | Keep the value, keep the line under review, and when exactly one single-decimal-point reading reproduces the printed amount, offer it via the existing `suggestions` / `suggested_rate` fields; review table shows issues and a **"Use ₹58.75 as rate"** button (never applied automatically) | `services/invoice.py`, `src/pages/InvoiceScanner.tsx` |
| 4 | Low-light photos unreadable even after preparation | Brightening multiplied sensor grain ×3.5; the grain was then enlarged by the geometric warp into blobs that denoising cannot remove; the existing preprocessor's CLAHE amplified it and its Hough deskew rotated straight pages by 44° | Denoise dark, grainy photos at native resolution before any warp; noise re-measured on the paper after brightening | `document_prep/enhancement.py`, `pipeline.py` |
| 5 | Retake not advised for unrecoverable small/blurry captures | Advice used post-enhancement metrics, which enlargement can make look good | Retake advice from the capture grade (POOR/UNREADABLE), cut-off, or an unreadable OCR test reading | `document_prep/pipeline.py` |

Not changed (reported only): the existing review screen invents an invoice number
(`'INV-' + random`), "Generic Supplier" and today's date when they are missing. This would defeat
the duplicate-invoice check on confirm. Changing it alters the existing workflow, so it needs approval.

## 4. HEIC/HEIF
`pi-heif` (decode-only; 1.5 MB wheel; BSD-3 binding over LGPL libheif/libde265; no GPL x265
encoder; `pillow-heif` would be 5.7 MB and bundles encoders). Format detected by `ftyp` brand
(AVIF rejected), pixel cap checked before decoding, the decoder applies HEIF rotation itself and
records it in `original_orientation` (never rotated twice), alpha flattened. Fixtures were generated
once with `pillow-heif` (not a runtime dependency). JPG/PNG paths unchanged (tested).

## 5. Mobile validation
`scripts/e2e/mobile_capture_check.cjs`: Playwright, Pixel 7 emulation, Chromium fake camera fed with
a video of a photographed invoice. **25/25 checks passed** (run twice; second time from the committed
location): permission granted + live preview, 2 camera captures, multi-photo gallery upload,
automatic upright turn, rotate right/180/left/reset, replace (position kept), remove, reorder,
3-page PDF download, extraction to review table, original-photo fallback, permission denied
(message + fallback to the phone camera), camera API unavailable (native `capture` input),
invalid file, corrupt image, server error + retry, 48 px touch targets.

**Not tested: a physical Android device.** No device or attached computer was available, the
Android SDK download is blocked by the network policy, and there is no KVM for an emulator, so the
Capacitor WebView, real camera hardware, Android permission dialogs and the native camera intent
have not been exercised. The Capacitor source in `node_modules` confirms the WebView grants
`getUserMedia` camera requests (CAMERA permission is in the manifest) and supports `capture` file
inputs. Observed (pre-existing): at phone width the quantity cell of the review table is clipped.

## 6. Test execution (all executed)

| Suite | Result |
|---|---|
| Full backend suite (`pytest`, includes all existing invoice, inventory, sales, voice, auth tests) | **523 passed, 7 skipped** (the same 7 pre-existing skips: fixture files absent) |
| Document preparation unit + API + HEIC + issue-fix tests | included above (core 48, API 11, OCR acceptance 28, HEIC 8, fixes 18) |
| Frontend `vitest` | **63 passed** |
| TypeScript `tsc -b` | passed |
| `oxlint` | no findings in changed files |
| Production build `vite build` | passed |
| Mobile e2e | 25/25 |

## 7. V-model traceability

| Change | Verification (unit / integration) | Validation (measured) |
|---|---|---|
| PDF raw-stream image skip | `test_extraction_issue_fixes.py` ×3; `test_pdf_pixels_are_never_mistaken_for_a_text_layer`; existing PDF/OCR suites | digital fixtures unchanged; reproduction PDF now image |
| Header parsing | `test_split_title_and_clipped_invoice_label`, 4 existing-layout cases, no-fallback case | real pipeline run: supplier + invoice no. correct |
| Decimal suggestion | 8 candidate tests + API test (value kept, review, suggestion) | end-to-end run: 58575 kept, ₹58.75 offered |
| HEIC | `test_document_prep_heic.py` ×8 + API HEIC test | – (no real HEIC photos) |
| Low-light native denoise | `test_dark_grainy_photo_is_denoised_before_resampling`, `test_normal_photo_is_not_denoised` | low light 0 → 32/51 lines |
| Retake from capture | `test_retake_follows_the_capture_not_the_enhanced_metrics` | 18/20 hard cases flagged |
| Camera error mapping | `invoiceCapture.test.ts` | mobile e2e 25/25 |

## 8. Production readiness
**Not yet production-ready for real phone capture.** The code paths are tested and regression-free,
but the accuracy claims rest on simulated captures. Before release:
1. run `real_world_validation.py --photos` on a set of real shop invoice photos (several phones,
   lighting conditions and layouts) and review the numbers;
2. test on at least one physical Android device (camera permission, capture, upload over mobile data);
3. decide on the review screen's invented invoice number/supplier/date (section 3).

Other limitations: blurry and small-text captures are rarely recoverable (retake advised);
preparation took about 5–15 s per page in these runs; a measured 3-page PDF of colour pages was
10 MB, so by extrapolation the 25 MB OCR limit is reached at about 7 colour pages, beyond which pages
fall back to JPEG q95 (not measured); Indian scripts other than Latin were not evaluated.
