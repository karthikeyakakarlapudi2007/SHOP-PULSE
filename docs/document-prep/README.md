# Invoice photo preparation layer

A separate preprocessing stage in front of the existing invoice OCR engine. It turns phone
photos (sideways, upside down, tilted, shot at an angle, in shadow or low light, small or
soft) into clean, upright page images. It lets the shop owner check and correct every page,
builds a PDF of the real page pixels, and sends that PDF to the **unchanged** OCR extraction.

The OCR engine (`services/grocery_ocr`, `services/ocr.py`, `services/ocr_worker.mjs`) and
`POST /api/v1/invoices/extract` are not modified. The new layer only *calls* the existing
engine: for evidence (which orientation or version reads best), and for extraction (the same
`services.invoice.extract_invoice_from_bytes` used by `/invoices/extract`).

## Flow

```
Camera / photos (multi-page)                       frontend: DocumentPrepWorkflow + CameraCapture
   │  POST /document-prep/sessions/{id}/pages       (one request per page, processed in order)
   ▼
loader.py           magic-byte check, pixel cap from header (decompression bombs), JPEG draft
                    decode for huge photos, EXIF orientation applied exactly once
document_detector   edge-loop / brightness / colour-distance outline candidates, validated by
                    edge support, boundary contrast and "no text outside" → perspective warp
                    (true aspect ratio via Zhang & He), or keep the framing if not reliable
orientation.py      text-line direction from character neighbours (docstrum) → 0/180 vs 90/270;
                    up vs down from OCR readability (existing engine) + ascender/descender evidence
deskew              projection-profile angle, rotation on an expanded canvas (nothing clipped);
                    small text is enlarged inside the same warp (one resampling)
verification        residual tilt < 1.5°, lines horizontal, ≥ 80 % of characters preserved,
                    otherwise geometry is reverted
quality.py          resolution, blur (edge spread + normalised Laplacian), brightness, contrast,
                    noise (Immerkær), shadows, perspective, rotation, text cut off at the photo edge
enhancement.py      only measured problems are treated: illumination, denoise, upscale, contrast,
                    CLAHE (very faint print), selective sharpening; result verified (characters and
                    decimal points/dots must survive) or reduced / abandoned
variants            original · corrected (colour) · enhanced · binarized (difficult pages only)
selection           each version read by the existing engine; score = confident words + 30 per
                    table row where quantity × rate = amount; ties keep the corrected page
   ▼
Preview & manual correction    rotate left / right / 180 / reset, choose version, retake, replace,
                               remove, reorder, undo automatic corrections per page
   ▼
pdf_builder.py      one page per image, page order kept, page size = image at 300 DPI, lossless
   ▼
POST /document-prep/sessions/{id}/extract  →  existing extraction  →  existing review table
                    originals + submitted PDF archived; "read the original photos instead" fallback
```

## API (`/api/v1/document-prep`, authenticated, per user)

| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions` | start a scan |
| GET / DELETE | `/sessions/{sid}` | session state / discard |
| POST | `/sessions/{sid}/pages` | upload one photo (multipart `file`; `auto_orientation`, `perspective`, `enhance` query flags) |
| POST | `/sessions/{sid}/pages/{pid}/reprocess` | re-run from the stored original with other options |
| PATCH | `/sessions/{sid}/pages/{pid}` | `rotation` (0/90/180/270), `rotate_by` (−90/90/180/270), `selected_variant` |
| DELETE | `/sessions/{sid}/pages/{pid}` | remove a page |
| PUT | `/sessions/{sid}/order` | `{"page_ids": [...]}` |
| GET | `/sessions/{sid}/pages/{pid}/image?variant=&size=thumb\|preview\|full` | private preview (manual rotation applied) |
| GET | `/sessions/{sid}/pages/{pid}/original` | the photo exactly as uploaded |
| POST | `/sessions/{sid}/pdf` | `{"source": "processed"\|"original"}` → PDF |
| POST | `/sessions/{sid}/extract` | `{"source": ...}` → `{"extraction": <same body as /invoices/extract>, "preparation": {...}}` |

## Safety and performance

* File type is decided by magic bytes; extensions are only allow-listed; names are display-only.
* Pixel count is checked from the header before decoding (60 MP cap). JPEGs larger than twice
  the 3400 px working size are decoded at reduced scale. Uploads are capped at 25 MB and read in chunks.
* Storage paths are built only from server-generated 32-hex ids under the user's own folder; the
  resolved path must stay inside the storage root. Another user's session id returns 404.
* Manifests are written atomically under a per-session lock (safe concurrent uploads).
* At most `DOC_PREP_MAX_CONCURRENT_JOBS` (default 2) pages are processed at once, in a thread
  pool, so other API requests are not blocked; extra requests wait up to 90 s, then get 503.
* Sessions expire after `DOC_PREP_SESSION_TTL_SECONDS` (6 h) and are swept on every new session.
* Originals are never modified. After extraction the originals and the submitted PDF are kept in
  `backend/storage/invoice_documents/<user>/<invoice>_<session>/` (git-ignored, not web-served).

Configuration: `backend/services/document_prep/config.py` (all values overridable with
`DOC_PREP_*` environment variables, e.g. `DOC_PREP_OCR_ORIENTATION=false` to skip OCR evidence).

## PDF details

* Pages are stored losslessly (Flate). Very large colour photos fall back to JPEG q=95 (4:4:4) only if
  a multi-page PDF would otherwise exceed 25 MB; the encoding of every page is reported.
* Image streams are additionally ASCII-hex wrapped. **Reason:** the existing PDF reader
  (`BasePDFProcessor._extract_raw_pdf_stream_text`) inflates every stream, including image data, and
  scans it for text operators. Compressed pixels can match by chance; this was observed producing
  garbage "digital text" during development. Hex text cannot match. The bug in the existing reader
  is left untouched (see limitations).
* The existing pipeline rasterises PDFs with pdfium at 300 DPI. Where a page size within 48 px
  maps to a whole number of points with an exact bitmap size, the page is padded to it (paper
  colour, right/bottom) and the rasterised page is **pixel-identical** to the prepared image. For other
  sizes, dimensions still match but pdfium resamples by a fraction of a pixel (measured OCR
  difference within noise).

## Tests and evaluation

| File | What it checks |
|---|---|
| `backend/tests/doc_prep_dataset.py` | deterministic dataset: 17 cases (incl. all 15 required types) with exact ground truth |
| `backend/tests/test_document_prep_core.py` | EXIF, input safety, orientation, deskew 1/3/5/8°, no clipping, perspective + aspect ratio, quality grades, paper texture, cut-off, enhancement safety (decimal points), PDF order/pixels, storage security |
| `backend/tests/test_document_prep_api.py` | full API flow, isolation, invalid uploads, limits, real end-to-end extraction + archive + original fallback |
| `backend/tests/test_document_prep_ocr.py` | measured: prepared page reads at least as well as the original on every case; rotation with OCR evidence |
| `backend/tests/evaluate_document_prep.py` | CER / WER / word recall / critical-token recall report → `ocr_comparison.md` |
| `backend/tests/evaluate_fixture_extraction.py` | correct line items on the real fixtures, today vs prepared → `fixture_extraction_results.md` |
| `src/tests/invoiceCapture.test.ts` | frontend helpers and API client |

Run: `cd backend && .venv/bin/python -m pytest tests/test_document_prep_*.py` and `npm test`.
