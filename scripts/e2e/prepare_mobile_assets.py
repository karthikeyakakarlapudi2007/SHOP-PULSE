"""Create the assets used by mobile_capture_check.cjs in OUT_DIR:
cam.y4m (fake camera video of a photographed invoice), gallery_p2.jpg, gallery_p3.jpg.

    backend/.venv/bin/python scripts/e2e/prepare_mobile_assets.py OUT_DIR
"""
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "tests"))
from real_world_validation import photograph  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
fx = ROOT / "backend" / "tests" / "fixtures" / "ground_truth"
gt = json.loads((fx / "ground_truth.json").read_text(encoding="utf-8"))
p1 = cv2.imread(str(fx / "invoices" / gt["TC24_dairy_and_staples"]["filename"]))
p2 = cv2.imread(str(fx / "invoices" / gt["TC29_flours_and_pulses"]["filename"]))
frame = cv2.resize(cv2.imdecode(np.frombuffer(photograph(p1, "tilted", 5), np.uint8), 1), (1600, 1200))
cv2.imwrite(str(out / "cam_frame.png"), frame)
cv2.imwrite(str(out / "gallery_p2.jpg"), cv2.imdecode(np.frombuffer(photograph(p2, "upside_down", 9), np.uint8), 1))
cv2.imwrite(str(out / "gallery_p3.jpg"), cv2.imdecode(np.frombuffer(photograph(p1, "shadow", 11), np.uint8), 1))
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-loop", "1", "-i", str(out / "cam_frame.png"), "-t", "2",
                "-r", "10", "-pix_fmt", "yuv420p", str(out / "cam.y4m")], check=True)
print(f"assets written to {out}")
