"""Assets for direct_upload_warning_check.cjs: a clear and a poor synthetic invoice photo + a PDF."""
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "tests"))
from doc_prep_dataset import build_dataset  # noqa: E402
from services.document_prep.pdf_builder import build_pdf  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
ds = build_dataset()
cv2.imwrite(str(out / "clear.jpg"), ds["01_clear_portrait"].pages[0])
cv2.imwrite(str(out / "poor.jpg"), ds["17_unrecoverable"].pages[0])
(out / "clear.pdf").write_bytes(build_pdf([ds["01_clear_portrait"].pages[0]]).data)
print("ok", out)
