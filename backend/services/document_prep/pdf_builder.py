"""
Image-to-PDF generation for prepared invoice pages.

A minimal, dependency-free PDF writer that embeds the actual page pixels:

* one page per image, in the given order, page size = image size at `dpi`, no margins;
* grayscale and colour pages are stored losslessly (Flate/zlib), ASCII-hex wrapped so no
  PDF reader can mistake pixel data for a text layer;
* very large colour photographs fall back to high-quality JPEG (q=95, no chroma
  subsampling) so a multi-page PDF stays within the OCR upload limit.  The encoding used
  for every page is reported.

Page size is chosen so that the existing OCR pipeline, which rasterises PDFs at 300 DPI,
gets back exactly the same pixel dimensions that were prepared.

Note: converting to PDF does not improve image clarity; all improvement happens earlier, in
preprocessing.
"""

from __future__ import annotations

import io
import math
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np


@dataclass
class PdfPageInfo:
    index: int
    width_px: int
    height_px: int
    encoding: str  # flate-gray | flate-rgb | jpeg-rgb | jpeg-gray
    bytes: int
    padded_right_px: int = 0
    padded_bottom_px: int = 0
    pixel_exact: bool = True  # rasterising at dpi returns exactly these pixels


@dataclass
class PdfResult:
    data: bytes
    pages: List[PdfPageInfo]
    dpi: int


def _exact_pixels(pixels: int, dpi: int) -> int:
    """Smallest size >= pixels that is a whole number of points and renders back exactly."""
    unit = dpi // math.gcd(dpi, 72)  # pixels per whole-point step (25 at 300 DPI)
    scale = dpi / 72.0
    size = -(-pixels // unit) * unit
    for _ in range(200):
        if math.ceil((size * 72 // dpi) * scale) == size:
            return size
        size += unit
    return size


MAX_EXACT_PAD = 48


def _nearest_page_points(pixels: int, dpi: int) -> float:
    """Largest float32 point size whose rendering at dpi/72 is exactly `pixels` wide."""
    scale = dpi / 72.0
    pt = np.float32(pixels * 72.0 / dpi)
    for _ in range(64):
        if math.ceil(float(pt) * scale) <= pixels:
            break
        pt = np.nextafter(pt, np.float32(0))
    return float(pt)


def _paper_fill(img: np.ndarray):
    strip = np.concatenate([img[-3:].reshape(-1, *img.shape[2:]), img[:, -3:].reshape(-1, *img.shape[2:])])
    med = np.median(strip, axis=0)
    return int(med) if np.ndim(med) == 0 else tuple(int(v) for v in med)


def _encode_image(img: np.ndarray, allow_jpeg: bool, flate_budget: int) -> Tuple[bytes, dict, str]:
    """Return (stream bytes, image dictionary entries, encoding name)."""
    h, w = img.shape[:2]
    if img.ndim == 3 and img.shape[2] == 3:
        b, g, r = cv2.split(img)
        if np.array_equal(b, g) and np.array_equal(g, r):
            img = b  # colour image that is actually gray
    if img.ndim == 2:
        data = zlib.compress(np.ascontiguousarray(img).tobytes(), 6)
        if len(data) <= flate_budget or not allow_jpeg:
            return data, {"ColorSpace": "/DeviceGray", "BitsPerComponent": 8, "Filter": "/FlateDecode"}, "flate-gray"
        ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return enc.tobytes(), {"ColorSpace": "/DeviceGray", "BitsPerComponent": 8, "Filter": "/DCTDecode"}, "jpeg-gray"
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    data = zlib.compress(np.ascontiguousarray(rgb).tobytes(), 6)
    if len(data) <= flate_budget or not allow_jpeg:
        return data, {"ColorSpace": "/DeviceRGB", "BitsPerComponent": 8, "Filter": "/FlateDecode"}, "flate-rgb"
    params = [cv2.IMWRITE_JPEG_QUALITY, 95]
    if hasattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR"):
        params += [cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444]
    ok, enc = cv2.imencode(".jpg", img, params)
    return enc.tobytes(), {"ColorSpace": "/DeviceRGB", "BitsPerComponent": 8, "Filter": "/DCTDecode"}, "jpeg-rgb"


def build_pdf(
    images: Sequence[np.ndarray],
    dpi: int = 300,
    title: Optional[str] = None,
    max_bytes: Optional[int] = None,
    allow_jpeg: bool = True,
) -> PdfResult:
    if not images:
        raise ValueError("At least one page is required to build a PDF.")
    n = len(images)
    # Spread the size budget across pages; lossless unless a page would not fit.
    budget_total = max_bytes or 25 * 1024 * 1024
    flate_budget = int(budget_total * 0.9 / n / 2)  # streams are hex-encoded (2x) below

    out = io.BytesIO()
    offsets: List[int] = []

    def write_obj(num: int, body: bytes) -> None:
        while len(offsets) < num:
            offsets.append(0)
        offsets[num - 1] = out.tell()
        out.write(f"{num} 0 obj\n".encode("ascii"))
        out.write(body)
        out.write(b"\nendobj\n")

    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    # Object numbering: 1 catalog, 2 pages, 3 info, then 3 objects per page
    page_nums = [4 + i * 3 for i in range(n)]
    infos: List[PdfPageInfo] = []
    for i, img in enumerate(images):
        if img is None or img.size == 0:
            raise ValueError(f"Page {i + 1} is empty.")
        h, w = img.shape[:2]
        # The existing OCR pipeline rasterises with pdfium at scale dpi/72 into a bitmap of
        # ceil(page_size * scale) pixels.  A page of a whole number of points maps image pixels
        # 1:1 onto that bitmap (no resampling) when the size works out exactly, so pages are
        # padded right/bottom with paper colour (at most MAX_EXACT_PAD px) to such a size.
        # Where no exact size is that close, the page keeps its own size; the renderer then
        # resamples by a fraction of a pixel (dimensions still match).
        tw, th = _exact_pixels(w, dpi), _exact_pixels(h, dpi)
        exact = (tw - w) <= MAX_EXACT_PAD and (th - h) <= MAX_EXACT_PAD
        if exact:
            pad_w, pad_h = tw - w, th - h
            if pad_w or pad_h:
                img = cv2.copyMakeBorder(img, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=_paper_fill(img))
            pw, ph = repr(tw * 72 // dpi), repr(th * 72 // dpi)
        else:
            pad_w = pad_h = 0
            tw, th = w, h
            pw, ph = repr(_nearest_page_points(w, dpi)), repr(_nearest_page_points(h, dpi))
        stream, entries, encoding = _encode_image(img, allow_jpeg, flate_budget)
        page_no, content_no, image_no = page_nums[i], page_nums[i] + 1, page_nums[i] + 2
        content = f"q {pw} 0 0 {ph} 0 0 cm /Im0 Do Q".encode("ascii")
        write_obj(page_no, (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw} {ph}] "
            f"/Resources << /XObject << /Im0 {image_no} 0 R >> /ProcSet [/PDF /ImageB /ImageC] >> "
            f"/Contents {content_no} 0 R >>").encode("ascii"))
        write_obj(content_no, f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
        # Image data is additionally ASCII-hex encoded. The existing OCR pipeline's PDF reader
        # has a fallback that zlib-inflates every stream and scans it for text operators
        # (BT ... (text) Tj ... ET); compressed pixel data can contain such byte patterns by
        # chance and would then be mistaken for digital text. Hex text (0-9, A-F) can never
        # inflate or contain those operators. Still lossless; costs ~2x stream size.
        stream = stream.hex().upper().encode("ascii") + b">"
        entries = dict(entries)
        entries["Filter"] = f"[/ASCIIHexDecode {entries['Filter']}]"
        dict_entries = " ".join(f"/{k} {v}" for k, v in entries.items())
        write_obj(image_no, (
            f"<< /Type /XObject /Subtype /Image /Width {tw} /Height {th} {dict_entries} /Length {len(stream)} >>\nstream\n"
        ).encode("ascii") + stream + b"\nendstream")
        infos.append(PdfPageInfo(i + 1, w, h, encoding, len(stream), pad_w, pad_h, exact))

    kids = " ".join(f"{p} 0 R" for p in page_nums)
    write_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>")
    write_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("ascii"))
    now = datetime.now(timezone.utc).strftime("D:%Y%m%d%H%M%SZ")
    safe_title = "".join(ch for ch in (title or "Invoice scan") if ch.isalnum() or ch in " -_.")[:80]
    write_obj(3, f"<< /Title ({safe_title}) /Producer (ShopPulse document preparation) /CreationDate ({now}) >>".encode("ascii"))

    xref_pos = out.tell()
    total = len(offsets)
    out.write(f"xref\n0 {total + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(f"trailer\n<< /Size {total + 1} /Root 1 0 R /Info 3 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii"))
    data = out.getvalue()
    if max_bytes and len(data) > max_bytes:
        raise ValueError(
            f"The PDF would be {len(data) // (1024 * 1024)} MB, above the {max_bytes // (1024 * 1024)} MB limit. "
            "Remove a page or use fewer photos.")
    return PdfResult(data, infos, dpi)
