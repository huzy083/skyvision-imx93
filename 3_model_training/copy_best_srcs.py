#!/usr/bin/env python3
"""Reproduce the top-4-per-class selection and copy the CLEAN originals to
/tmp/board_test_imgs so they can be run through the on-board NPU model."""
import shutil
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO

MODEL  = "/home/shing/uav_ground_station/runs/insplad/yolov8n_power_merged/weights/best.pt"
IMGDIR = Path("/home/shing/uav_ground_station/datasets/insplad/det/images/train")
OUT    = Path("/tmp/board_test_imgs")
IMGSZ, CONF, TOPN = 320, 0.35, 4

model = YOLO(MODEL)
names = model.names
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)

per_class = defaultdict(list)
for r in model.predict(source=str(IMGDIR), imgsz=IMGSZ, conf=CONF,
                       device=0, half=True, stream=True, verbose=False):
    if r.boxes is None:
        continue
    for b in r.boxes:
        per_class[int(b.cls)].append((float(b.conf), r.path))

n = 0
for c in range(len(names)):
    seen = []
    for conf, p in sorted(per_class.get(c, []), key=lambda x: -x[0]):
        if p in seen:
            continue
        seen.append(p)
        dst = OUT / f"{c:02d}_{names[c].replace(' ', '_')}__{len(seen)}__{Path(p).name}"
        shutil.copy(p, dst)
        n += 1
        if len(seen) >= TOPN:
            break
print(f"copied {n} clean source images to {OUT}", flush=True)
