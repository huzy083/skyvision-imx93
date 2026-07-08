#!/usr/bin/env python3
"""Score every training image by the float model (sum of det confidences) and
copy the top-N clean originals as candidates for on-board ranking."""
import shutil
from pathlib import Path
from ultralytics import YOLO

MODEL  = "/home/shing/uav_ground_station/runs/insplad/yolov8n_power_merged/weights/best.pt"
IMGDIR = Path("/home/shing/uav_ground_station/datasets/insplad/det/images/train")
OUT    = Path("/tmp/board_cand")
IMGSZ, CONF, TOPN = 320, 0.5, 120

model = YOLO(MODEL)
scored = []
for r in model.predict(source=str(IMGDIR), imgsz=IMGSZ, conf=CONF,
                       device=0, half=True, stream=True, verbose=False):
    if r.boxes is None or len(r.boxes) == 0:
        continue
    scored.append((float(sum(b.conf for b in r.boxes)), r.path))

scored.sort(key=lambda x: -x[0])
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
for i, (s, p) in enumerate(scored[:TOPN]):
    shutil.copy(p, OUT / f"cand{i:03d}__{Path(p).name}")
print(f"copied {min(TOPN, len(scored))} candidates (top float score {scored[0][0]:.2f}) to {OUT}", flush=True)
