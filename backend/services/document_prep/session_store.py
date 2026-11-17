"""
Per-user, on-disk storage for capture sessions (multi-page invoice preparation).

Security
* Every path is built from server-generated 32-hex identifiers only; identifiers from
  requests are validated against that pattern and the resolved path must stay inside the
  storage root, so path traversal is impossible.
* Sessions live under the owner's user id; another user's session id simply does not exist
  for the caller.
* Uploaded file names are never used as paths (display only).
* Sessions expire (TTL) and are removed by a sweep that runs on every session creation.

Durability
* The uploaded bytes are stored unchanged ("original.bin") and are never modified.
* The manifest is written atomically (temp file + os.replace) under a per-session lock, so
  concurrent page uploads to one session cannot lose updates.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import cv2
import numpy as np

from services.document_prep.config import DocumentPrepConfig, default_config

_ID = re.compile(r"^[0-9a-f]{32}$")
VARIANT_NAMES = ("original", "corrected", "enhanced", "binarized")
ROTATIONS = (0, 90, 180, 270)
PREVIEW_MAX_SIDE = 1400
THUMB_MAX_SIDE = 360


class SessionNotFound(LookupError):
    pass


class SessionLimitError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


def check_id(value: str, kind: str = "id") -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise SessionNotFound(f"Unknown {kind}.")
    return value


def owner_key(user_id: Any) -> str:
    """Directory name for a user: hex of their UUID (never user-controlled text)."""
    try:
        return uuid.UUID(str(user_id)).hex
    except (ValueError, TypeError, AttributeError):
        return hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:32]


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _resize_max(img: np.ndarray, max_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img
    s = max_side / float(max(h, w))
    return cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)


def rotate_cw(img: np.ndarray, degrees: int) -> np.ndarray:
    k = (int(degrees) // 90) % 4
    if k == 0:
        return img
    return cv2.rotate(img, {1: cv2.ROTATE_90_CLOCKWISE, 2: cv2.ROTATE_180, 3: cv2.ROTATE_90_COUNTERCLOCKWISE}[k])


class SessionStore:
    def __init__(self, config: DocumentPrepConfig = default_config, root: Optional[Path] = None):
        self.config = config
        self.root = Path(root or config.storage_dir).resolve()
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ---- paths & locks -------------------------------------------------------------------
    def _safe(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts).resolve()
        if p != self.root and self.root not in p.parents:
            raise SessionNotFound("Invalid path.")
        return p

    def _session_dir(self, user_id: Any, session_id: str) -> Path:
        return self._safe(owner_key(user_id), check_id(session_id, "session"))

    def _page_dir(self, user_id: Any, session_id: str, page_id: str) -> Path:
        return self._safe(owner_key(user_id), check_id(session_id, "session"), "pages", check_id(page_id, "page"))

    @contextmanager
    def _lock(self, session_id: str) -> Iterator[None]:
        with self._locks_guard:
            lock = self._locks.setdefault(session_id, threading.Lock())
        with lock:
            yield

    # ---- manifest --------------------------------------------------------------------------
    def _read_manifest(self, sdir: Path) -> Dict[str, Any]:
        mf = sdir / "manifest.json"
        if not mf.is_file():
            raise SessionNotFound("This scanning session has expired or does not exist. Please start again.")
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        if time.time() - float(manifest.get("updated_at", 0)) > self.config.session_ttl_seconds:
            raise SessionNotFound("This scanning session has expired. Please start again.")
        return manifest

    def _write_manifest(self, sdir: Path, manifest: Dict[str, Any]) -> None:
        manifest["updated_at"] = time.time()
        _write_atomic(sdir / "manifest.json", json.dumps(manifest, indent=1, default=str).encode("utf-8"))

    # ---- sessions --------------------------------------------------------------------------
    def create_session(self, user_id: Any) -> Dict[str, Any]:
        self.cleanup_expired()
        user_dir = self._safe(owner_key(user_id))
        user_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted((p for p in user_dir.iterdir() if p.is_dir() and _ID.match(p.name)),
                          key=lambda p: p.stat().st_mtime)
        while len(existing) >= self.config.max_sessions_per_user:
            shutil.rmtree(existing.pop(0), ignore_errors=True)  # drop the oldest unfinished session
        sid = new_id()
        sdir = self._session_dir(user_id, sid)
        (sdir / "pages").mkdir(parents=True, exist_ok=False)
        manifest = {"session_id": sid, "owner": owner_key(user_id), "created_at": time.time(), "pages": []}
        self._write_manifest(sdir, manifest)
        return manifest

    def get_session(self, user_id: Any, session_id: str) -> Dict[str, Any]:
        return self._read_manifest(self._session_dir(user_id, session_id))

    def delete_session(self, user_id: Any, session_id: str) -> None:
        sdir = self._session_dir(user_id, session_id)
        if not (sdir / "manifest.json").is_file():
            raise SessionNotFound("Unknown session.")
        shutil.rmtree(sdir, ignore_errors=True)
        with self._locks_guard:
            self._locks.pop(session_id, None)

    def cleanup_expired(self) -> int:
        if not self.root.exists():
            return 0
        removed = 0
        now = time.time()
        for user_dir in self.root.iterdir():
            if not user_dir.is_dir():
                continue
            for sdir in user_dir.iterdir():
                if not sdir.is_dir() or not _ID.match(sdir.name):
                    continue
                mf = sdir / "manifest.json"
                try:
                    age = now - (json.loads(mf.read_text(encoding="utf-8")).get("updated_at", 0) if mf.is_file() else sdir.stat().st_mtime)
                except (OSError, ValueError):
                    age = now - sdir.stat().st_mtime
                if age > self.config.session_ttl_seconds:
                    shutil.rmtree(sdir, ignore_errors=True)
                    removed += 1
        return removed

    # ---- pages -----------------------------------------------------------------------------
    def reserve_page_slot(self, user_id: Any, session_id: str) -> None:
        manifest = self.get_session(user_id, session_id)
        if len(manifest["pages"]) >= self.config.max_pages_per_session:
            raise SessionLimitError(f"A scan can have at most {self.config.max_pages_per_session} pages.")

    def save_page(
        self,
        user_id: Any,
        session_id: str,
        original_bytes: bytes,
        filename: str,
        mime: str,
        variants: Dict[str, np.ndarray],
        recommended: str,
        metadata: Dict[str, Any],
        page_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a processed page. With page_id, replaces the processed outputs of that page
        (re-processing) while keeping its original bytes and position."""
        sdir = self._session_dir(user_id, session_id)
        is_new = page_id is None
        pid = page_id or new_id()
        pdir = self._page_dir(user_id, session_id, pid)
        pdir.mkdir(parents=True, exist_ok=True)
        if is_new:
            _write_atomic(pdir / "original.bin", original_bytes)
        for name in VARIANT_NAMES:
            for suffix in (".png", ".preview.jpg", ".thumb.jpg"):
                stale = pdir / f"{name}{suffix}"
                if name not in variants and stale.exists():
                    stale.unlink()
        for name, img in variants.items():
            if name not in VARIANT_NAMES:
                continue
            ok, enc = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            if not ok:
                raise ValueError("Could not store processed page.")
            _write_atomic(pdir / f"{name}.png", enc.tobytes())
            prev = _resize_max(img, PREVIEW_MAX_SIDE)
            _write_atomic(pdir / f"{name}.preview.jpg", cv2.imencode(".jpg", prev, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes())
            thumb = _resize_max(img, THUMB_MAX_SIDE)
            _write_atomic(pdir / f"{name}.thumb.jpg", cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes())

        with self._lock(session_id):
            manifest = self._read_manifest(sdir)
            pages: List[Dict[str, Any]] = manifest["pages"]
            if is_new and len(pages) >= self.config.max_pages_per_session:
                shutil.rmtree(pdir, ignore_errors=True)
                raise SessionLimitError(f"A scan can have at most {self.config.max_pages_per_session} pages.")
            entry = next((p for p in pages if p["page_id"] == pid), None)
            record = {
                "page_id": pid,
                "filename": filename,
                "mime": mime,
                "size_bytes": len(original_bytes) if is_new else (entry or {}).get("size_bytes"),
                "sha256": hashlib.sha256(original_bytes).hexdigest() if is_new else (entry or {}).get("sha256"),
                "variants": [v for v in VARIANT_NAMES if v in variants],
                "recommended_variant": recommended,
                "selected_variant": recommended,
                "manual_rotation": 0,
                "metadata": metadata,
                "created_at": time.time() if is_new else (entry or {}).get("created_at", time.time()),
            }
            if entry is None:
                pages.append(record)
            else:
                pages[pages.index(entry)] = record
            self._write_manifest(sdir, manifest)
            return record

    def update_page(self, user_id: Any, session_id: str, page_id: str, *, rotation: Optional[int] = None,
                    rotate_by: Optional[int] = None, selected_variant: Optional[str] = None) -> Dict[str, Any]:
        sdir = self._session_dir(user_id, session_id)
        check_id(page_id, "page")
        with self._lock(session_id):
            manifest = self._read_manifest(sdir)
            entry = next((p for p in manifest["pages"] if p["page_id"] == page_id), None)
            if entry is None:
                raise SessionNotFound("Unknown page.")
            if rotation is not None:
                if rotation % 90 != 0:
                    raise ValueError("Rotation must be a multiple of 90 degrees.")
                entry["manual_rotation"] = int(rotation) % 360
            if rotate_by is not None:
                if rotate_by % 90 != 0:
                    raise ValueError("Rotation must be a multiple of 90 degrees.")
                entry["manual_rotation"] = (int(entry.get("manual_rotation", 0)) + int(rotate_by)) % 360
            if selected_variant is not None:
                if selected_variant not in entry["variants"]:
                    raise ValueError(f"Version '{selected_variant}' is not available for this page.")
                entry["selected_variant"] = selected_variant
            self._write_manifest(sdir, manifest)
            return entry

    def delete_page(self, user_id: Any, session_id: str, page_id: str) -> Dict[str, Any]:
        sdir = self._session_dir(user_id, session_id)
        pdir = self._page_dir(user_id, session_id, page_id)
        with self._lock(session_id):
            manifest = self._read_manifest(sdir)
            before = len(manifest["pages"])
            manifest["pages"] = [p for p in manifest["pages"] if p["page_id"] != page_id]
            if len(manifest["pages"]) == before:
                raise SessionNotFound("Unknown page.")
            self._write_manifest(sdir, manifest)
        shutil.rmtree(pdir, ignore_errors=True)
        return manifest

    def reorder(self, user_id: Any, session_id: str, page_ids: List[str]) -> Dict[str, Any]:
        sdir = self._session_dir(user_id, session_id)
        with self._lock(session_id):
            manifest = self._read_manifest(sdir)
            current = {p["page_id"]: p for p in manifest["pages"]}
            if sorted(page_ids) != sorted(current) or len(set(page_ids)) != len(page_ids):
                raise ValueError("The new order must list every page exactly once.")
            manifest["pages"] = [current[pid] for pid in page_ids]
            self._write_manifest(sdir, manifest)
            return manifest

    # ---- page data ---------------------------------------------------------------------------
    def page_entry(self, user_id: Any, session_id: str, page_id: str) -> Dict[str, Any]:
        manifest = self.get_session(user_id, session_id)
        entry = next((p for p in manifest["pages"] if p["page_id"] == check_id(page_id, "page")), None)
        if entry is None:
            raise SessionNotFound("Unknown page.")
        return entry

    def original_bytes(self, user_id: Any, session_id: str, page_id: str) -> Tuple[bytes, Dict[str, Any]]:
        entry = self.page_entry(user_id, session_id, page_id)
        data = (self._page_dir(user_id, session_id, page_id) / "original.bin").read_bytes()
        return data, entry

    def variant_image(self, user_id: Any, session_id: str, page_id: str, variant: str,
                      apply_rotation: bool = True) -> np.ndarray:
        entry = self.page_entry(user_id, session_id, page_id)
        if variant not in entry["variants"]:
            raise SessionNotFound("Unknown page version.")
        img = cv2.imread(str(self._page_dir(user_id, session_id, page_id) / f"{variant}.png"), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise SessionNotFound("Page image is missing.")
        return rotate_cw(img, entry.get("manual_rotation", 0)) if apply_rotation else img

    def preview_jpeg(self, user_id: Any, session_id: str, page_id: str, variant: str, size: str = "preview") -> bytes:
        entry = self.page_entry(user_id, session_id, page_id)
        if variant not in entry["variants"]:
            raise SessionNotFound("Unknown page version.")
        suffix = ".thumb.jpg" if size == "thumb" else ".preview.jpg"
        path = self._page_dir(user_id, session_id, page_id) / f"{variant}{suffix}"
        data = path.read_bytes()
        rot = int(entry.get("manual_rotation", 0)) % 360
        if rot:
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
            data = cv2.imencode(".jpg", rotate_cw(img, rot), [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes()
        return data

    # ---- archive -----------------------------------------------------------------------------
    def archive(self, user_id: Any, session_id: str, reference: str, pdf_bytes: bytes,
                extra: Optional[Dict[str, Any]] = None) -> str:
        """Keep the original uploads + the PDF sent to OCR after extraction (not web-served)."""
        manifest = self.get_session(user_id, session_id)
        safe_ref = re.sub(r"[^A-Za-z0-9_-]", "_", reference)[:64] or new_id()
        archive_root = Path(self.config.archive_dir).resolve()
        adir = (archive_root / owner_key(user_id) / f"{safe_ref}_{session_id[:8]}").resolve()
        if archive_root not in adir.parents:
            raise SessionNotFound("Invalid archive path.")
        adir.mkdir(parents=True, exist_ok=True)
        for i, page in enumerate(manifest["pages"], start=1):
            src = self._page_dir(user_id, session_id, page["page_id"]) / "original.bin"
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/bmp": ".bmp",
                   "image/tiff": ".tif"}.get(page.get("mime", ""), ".bin")
            shutil.copyfile(src, adir / f"page{i:02d}_original{ext}")
        _write_atomic(adir / "submitted_to_ocr.pdf", pdf_bytes)
        summary = {
            "session_id": session_id,
            "reference": reference,
            "archived_at": time.time(),
            "pages": [{k: p.get(k) for k in ("page_id", "filename", "sha256", "selected_variant", "manual_rotation",
                                             "recommended_variant")} for p in manifest["pages"]],
            **(extra or {}),
        }
        _write_atomic(adir / "manifest.json", json.dumps(summary, indent=1, default=str).encode("utf-8"))
        return adir.name
