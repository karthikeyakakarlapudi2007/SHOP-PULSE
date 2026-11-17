"""Create the invoice images used by invoice_metadata_check.cjs in OUT_DIR:
hdr_full.png (supplier, invoice number and date printed) and hdr_none.png (item table only).

    backend/.venv/bin/python scripts/e2e/prepare_metadata_assets.py OUT_DIR
"""
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tests"))
from doc_prep_dataset import PAGE_1_ITEMS, render_invoice_page  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
page = render_invoice_page(PAGE_1_ITEMS).image
cv2.imwrite(str(out / "hdr_full.png"), page)
cv2.imwrite(str(out / "hdr_none.png"), page[225:760])
print(f"assets written to {out}")
