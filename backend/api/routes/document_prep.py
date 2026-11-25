"""
Document preparation API: capture -> quality check -> automatic correction -> manual review
-> PDF -> existing OCR extraction.

Everything here sits in front of the existing invoice OCR. Extraction calls the same
service function as POST /invoices/extract (services.invoice.extract_invoice_from_bytes) with
the prepared PDF, so the OCR engine, its API contract and the review workflow are unchanged.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Literal, Optional

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import deps
from db.models.user import User
from services import invoice as invoice_service
from services import shop as shop_service
from services.document_prep.config import default_config
from services.document_prep.loader import ImageInputError, load_image, sniff_image_type, validate_filename
from services.document_prep.pdf_builder import build_pdf
from services.document_prep.pipeline import VARIANT_LABELS, PrepOptions, assess_capture, prepare_page
from services.document_prep.session_store import SessionLimitError, SessionNotFound, SessionStore
from services.grocery_ocr.exceptions import GroceryOCRError
from services.ocr import OcrUnavailableError

router = APIRouter()
logger = logging.getLogger(__name__)

store = SessionStore(default_config)
_jobs = threading.BoundedSemaphore(max(1, default_config.max_concurrent_jobs))
JOB_WAIT_SECONDS = 90
API_PREFIX = "/api/v1/document-prep"


# ---------------------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------------------


class PageUpdate(BaseModel):
    rotation: Optional[int] = Field(None, description="Absolute manual rotation, clockwise: 0, 90, 180 or 270")
    rotate_by: Optional[Literal[-90, 90, 180, 270]] = Field(None, description="Relative clockwise rotation")
    selected_variant: Optional[Literal["original", "corrected", "enhanced", "binarized"]] = None


class ReprocessOptions(BaseModel):
    auto_orientation: bool = True
    perspective: bool = True
    deskew: bool = True
    enhance: bool = True


class OrderUpdate(BaseModel):
    page_ids: List[str] = Field(..., min_length=1, max_length=50)


class OutputRequest(BaseModel):
    source: Literal["processed", "original"] = "processed"


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found.")


def _run_job(fn, *args, **kwargs):
    """CPU-heavy work with a cap on concurrent jobs, so scans never starve other requests."""
    if not _jobs.acquire(timeout=JOB_WAIT_SECONDS):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The scanner is busy with other photos. Please try again in a moment.")
    try:
        return fn(*args, **kwargs)
    finally:
        _jobs.release()


async def _read_upload(file: UploadFile) -> bytes:
    limit = default_config.max_upload_bytes
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail=f"The photo is larger than {limit // (1024 * 1024)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def page_summary(session_id: str, entry: Dict[str, Any], index: int) -> Dict[str, Any]:
    md = entry.get("metadata") or {}
    base = f"{API_PREFIX}/sessions/{session_id}/pages/{entry['page_id']}"
    working_size = None
    for st in md.get("steps", []):
        if st.get("step") == "exif_orientation":
            working_size = st.get("details", {}).get("working_size")
    orientation = md.get("orientation") or {}
    return {
        "page_id": entry["page_id"],
        "index": index,
        "filename": entry.get("filename"),
        "variants": [{"name": v, "label": VARIANT_LABELS.get(v, v)} for v in entry.get("variants", [])],
        "recommended_variant": entry.get("recommended_variant"),
        "selected_variant": entry.get("selected_variant"),
        "manual_rotation": entry.get("manual_rotation", 0),
        "auto_rotation_cw": orientation.get("auto_rotation_cw", 0),
        "orientation": orientation,
        "document": {**(md.get("document") or {}), "image_size": working_size},
        "quality_before": md.get("quality_before"),
        "quality_after": md.get("quality_after"),
        "enhancement": md.get("enhancement"),
        "selection": md.get("selection"),
        "steps": md.get("steps", []),
        "warnings": md.get("warnings", []),
        "retake_recommended": bool(md.get("retake_recommended")),
        "needs_confirmation": bool(orientation.get("needs_confirmation")),
        "needs_user_choice": bool(md.get("needs_user_choice")),
        "timings_ms": md.get("timings_ms", {}),
        "image_url": f"{base}/image",
        "original_url": f"{base}/original",
    }


def session_summary(manifest: Dict[str, Any]) -> Dict[str, Any]:
    sid = manifest["session_id"]
    pages = [page_summary(sid, p, i) for i, p in enumerate(manifest.get("pages", []))]
    return {
        "session_id": sid,
        "pages": pages,
        "page_count": len(pages),
        "limits": {
            "max_pages": default_config.max_pages_per_session,
            "max_upload_mb": default_config.max_upload_bytes // (1024 * 1024),
            "accepted_types": ["image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "image/bmp",
                               "image/tiff"],
        },
    }


def _session_images(user: User, session_id: str, source: str):
    manifest = store.get_session(user.id, session_id)
    if not manifest["pages"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one page first.")
    images = []
    for page in manifest["pages"]:
        if source == "original":
            data, entry = store.original_bytes(user.id, session_id, page["page_id"])
            images.append(cv2.cvtColor(load_image(data, entry.get("filename")).rgb, cv2.COLOR_RGB2BGR))
        else:
            images.append(store.variant_image(user.id, session_id, page["page_id"], page["selected_variant"]))
    return manifest, images


def _build_session_pdf(user: User, session_id: str, source: str):
    manifest, images = _session_images(user, session_id, source)
    try:
        result = build_pdf(images, dpi=default_config.pdf_dpi, title="Invoice scan",
                           max_bytes=default_config.max_pdf_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return manifest, result


# ---------------------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------------------


@router.post("/assess")
async def assess_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Photo-quality check for a directly uploaded invoice photo (no preparation, no OCR).

    Returns the same grade, issues and retake advice as the camera flow, so a poor or cut-off
    photo is reported before its extraction results are trusted."""
    data = await _read_upload(file)
    try:
        display_name = validate_filename(file.filename)
    except ImageInputError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    if sniff_image_type(data) is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="This file is not a supported photo. Please use JPG, PNG, HEIC, WEBP, BMP or TIFF.")
    try:
        return await run_in_threadpool(_run_job, lambda: assess_capture(data, display_name))
    except ImageInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Photo assessment failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"The photo could not be checked ({type(exc).__name__}).")


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(current_user: User = Depends(deps.get_current_user)) -> Any:
    """Start a capture session (one invoice, one or more pages)."""
    return session_summary(store.create_session(current_user.id))


@router.get("/sessions/{session_id}")
def get_session(session_id: str, current_user: User = Depends(deps.get_current_user)) -> Any:
    try:
        return session_summary(store.get_session(current_user.id, session_id))
    except SessionNotFound as exc:
        raise _not_found(exc)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, current_user: User = Depends(deps.get_current_user)) -> Response:
    try:
        store.delete_session(current_user.id, session_id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------------------


@router.post("/sessions/{session_id}/pages", status_code=status.HTTP_201_CREATED)
async def add_page(
    session_id: str,
    file: UploadFile = File(...),
    auto_orientation: bool = Query(True),
    perspective: bool = Query(True),
    enhance: bool = Query(True),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Upload one photo; it is analysed and corrected, and the original is kept unchanged."""
    try:
        store.reserve_page_slot(current_user.id, session_id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    except SessionLimitError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    data = await _read_upload(file)
    try:
        display_name = validate_filename(file.filename)
    except ImageInputError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    mime = sniff_image_type(data)
    if mime is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="This file is not a supported photo. Please use JPG, PNG, HEIC, WEBP, BMP or TIFF.")
    opts = PrepOptions(auto_orientation=auto_orientation, perspective=perspective, enhance=enhance)

    def work():
        prepared = prepare_page(data, display_name, opts)
        return store.save_page(current_user.id, session_id, data, display_name, mime, prepared.variants,
                               prepared.recommended_variant, prepared.metadata)

    try:
        entry = await run_in_threadpool(_run_job, work)
    except ImageInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except SessionNotFound as exc:
        raise _not_found(exc)
    except SessionLimitError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Page preparation failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"The photo could not be processed ({type(exc).__name__}). Please retake it.")
    manifest = store.get_session(current_user.id, session_id)
    index = next(i for i, p in enumerate(manifest["pages"]) if p["page_id"] == entry["page_id"])
    return page_summary(session_id, entry, index)


@router.post("/sessions/{session_id}/pages/{page_id}/reprocess")
async def reprocess_page(
    session_id: str,
    page_id: str,
    options: ReprocessOptions,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Re-run preparation from the stored original with different options (e.g. no automatic
    rotation, keep full photo). Manual rotation is reset."""
    try:
        data, entry = store.original_bytes(current_user.id, session_id, page_id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    opts = PrepOptions(auto_orientation=options.auto_orientation, perspective=options.perspective,
                       deskew=options.deskew, enhance=options.enhance)

    def work():
        prepared = prepare_page(data, entry.get("filename"), opts)
        return store.save_page(current_user.id, session_id, data, entry.get("filename"), entry.get("mime"),
                               prepared.variants, prepared.recommended_variant, prepared.metadata, page_id=page_id)

    try:
        new_entry = await run_in_threadpool(_run_job, work)
    except ImageInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except SessionNotFound as exc:
        raise _not_found(exc)
    manifest = store.get_session(current_user.id, session_id)
    index = next(i for i, p in enumerate(manifest["pages"]) if p["page_id"] == page_id)
    return page_summary(session_id, new_entry, index)


@router.patch("/sessions/{session_id}/pages/{page_id}")
def update_page(session_id: str, page_id: str, update: PageUpdate,
                current_user: User = Depends(deps.get_current_user)) -> Any:
    """Manual rotation (rotate left/right/180, reset with rotation=0) and version choice."""
    if update.rotation is not None and update.rotation not in (0, 90, 180, 270):
        raise HTTPException(status_code=422, detail="Rotation must be 0, 90, 180 or 270.")
    try:
        entry = store.update_page(current_user.id, session_id, page_id, rotation=update.rotation,
                                  rotate_by=update.rotate_by, selected_variant=update.selected_variant)
        manifest = store.get_session(current_user.id, session_id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    index = next(i for i, p in enumerate(manifest["pages"]) if p["page_id"] == page_id)
    return page_summary(session_id, entry, index)


@router.delete("/sessions/{session_id}/pages/{page_id}")
def delete_page(session_id: str, page_id: str, current_user: User = Depends(deps.get_current_user)) -> Any:
    try:
        return session_summary(store.delete_page(current_user.id, session_id, page_id))
    except SessionNotFound as exc:
        raise _not_found(exc)


@router.put("/sessions/{session_id}/order")
def reorder_pages(session_id: str, order: OrderUpdate, current_user: User = Depends(deps.get_current_user)) -> Any:
    try:
        return session_summary(store.reorder(current_user.id, session_id, order.page_ids))
    except SessionNotFound as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/sessions/{session_id}/pages/{page_id}/image")
def page_image(
    session_id: str,
    page_id: str,
    variant: Literal["original", "corrected", "enhanced", "binarized"] = Query("enhanced"),
    size: Literal["thumb", "preview", "full"] = Query("preview"),
    current_user: User = Depends(deps.get_current_user),
) -> Response:
    """Preview of one page version with the manual rotation applied (private, no caching)."""
    try:
        if size == "full":
            img = store.variant_image(current_user.id, session_id, page_id, variant)
            ok, enc = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            return Response(enc.tobytes(), media_type="image/png", headers={"Cache-Control": "private, no-store"})
        data = store.preview_jpeg(current_user.id, session_id, page_id, variant, size)
    except SessionNotFound as exc:
        raise _not_found(exc)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get("/sessions/{session_id}/pages/{page_id}/original")
def page_original(session_id: str, page_id: str, current_user: User = Depends(deps.get_current_user)) -> Response:
    """The photo exactly as uploaded (never modified)."""
    try:
        data, entry = store.original_bytes(current_user.id, session_id, page_id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/bmp": "bmp",
           "image/tiff": "tiff", "image/heic": "heic", "image/heif": "heif"}.get(entry.get("mime"), "bin")
    return Response(data, media_type=entry.get("mime") or "application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="invoice-page-{page_id[:8]}.{ext}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


# ---------------------------------------------------------------------------------------
# PDF + OCR
# ---------------------------------------------------------------------------------------


@router.post("/sessions/{session_id}/pdf")
async def session_pdf(session_id: str, request: OutputRequest,
                      current_user: User = Depends(deps.get_current_user)) -> Response:
    """Build the PDF of the selected page versions, in page order."""
    try:
        manifest, result = await run_in_threadpool(_run_job, _build_session_pdf, current_user, session_id, request.source)
    except SessionNotFound as exc:
        raise _not_found(exc)
    return Response(result.data, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="invoice-scan-{session_id[:8]}.pdf"',
        "Cache-Control": "private, no-store",
        "X-Page-Count": str(len(result.pages)),
    })


@router.post("/sessions/{session_id}/extract")
async def extract_from_session(
    session_id: str,
    request: OutputRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """Send the prepared document (or the untouched originals) to the existing OCR extraction.

    Returns {"extraction": <same body as POST /invoices/extract>, "preparation": {...}}.
    """
    shop, member = deps.get_current_shop_and_role(db, current_user)
    if member.role not in [deps.ShopRole.OWNER.value, deps.ShopRole.MANAGER.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to invoice scanning and preparation is restricted to Managers and Owners.",
        )
    try:
        manifest = store.get_session(current_user.id, session_id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    pages = manifest["pages"]
    if not pages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one page first.")

    def build():
        if request.source == "original" and len(pages) == 1:
            # Exactly what the scanner sent before this layer existed: the photo itself
            data, entry = store.original_bytes(current_user.id, session_id, pages[0]["page_id"])
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/bmp": ".bmp",
                   "image/tiff": ".tiff"}.get(entry.get("mime"))
            if ext:
                return data, f"invoice-photo{ext}", None
            # Formats the existing OCR upload does not accept (HEIC) go as a PDF of the
            # decoded original pixels, still without any correction.
            _, pdf = _build_session_pdf(current_user, session_id, "original")
            return pdf.data, "invoice-scan.pdf", pdf
        _, pdf = _build_session_pdf(current_user, session_id, request.source)
        return pdf.data, "invoice-scan.pdf", pdf

    try:
        document, doc_name, pdf = await run_in_threadpool(_run_job, build)
        extraction = await run_in_threadpool(
            invoice_service.extract_invoice_from_bytes,
            file_bytes=document, filename=doc_name, db=db, shop_id=shop.id)
    except SessionNotFound as exc:
        raise _not_found(exc)
    except OcrUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"OCR engine unavailable: {exc}")
    except (ValueError, GroceryOCRError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Extraction from prepared document failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Failed to extract invoice: {type(exc).__name__}")

    archive_id = None
    try:
        pdf_bytes = pdf.data if pdf is not None else _build_session_pdf(current_user, session_id, "original")[1].data
        archive_id = store.archive(current_user.id, session_id, getattr(extraction, "id", "invoice"), pdf_bytes,
                                   extra={"source": request.source})
    except Exception:  # archiving must never lose the extraction result
        logger.exception("Archiving prepared invoice failed")

    return {
        "extraction": extraction,
        "preparation": {
            "session_id": session_id,
            "source": request.source,
            "document_name": doc_name,
            "page_count": len(pages),
            "pages": [{"page_id": p["page_id"], "variant": p["selected_variant"] if request.source == "processed" else "original",
                       "manual_rotation": p.get("manual_rotation", 0),
                       "quality_before": (p.get("metadata") or {}).get("quality_before", {}).get("grade"),
                       "quality_after": (p.get("metadata") or {}).get("quality_after", {}).get("grade")}
                      for p in pages],
            "pdf_pages": [vars(pi) for pi in pdf.pages] if pdf is not None else None,
            "archived": archive_id is not None,
        },
    }
