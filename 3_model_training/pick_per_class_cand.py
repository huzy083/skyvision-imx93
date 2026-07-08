#!/usr/bin/env python3
"""Per-class candidate pool: for each class copy the float model's top-K images
(clean originals) so the board can then rank them per class."""
import shutil
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO

MODEL  = "/home/shing/uav_ground_station/runs/insplad/yolov8n_power_merged/weights/best.pt"
IMGDIR = Path("/home/shing/uav_ground_station/datasets/insplad/det/images/train")
OUT    = Path("/tmp/board_cand2")
IMGSZ, CONF, PERCLASS = 320, 0.4, 6

model = YOLO(MODEL)
names = model.names
per_class = defaultdict(list)
for r in model.predict(source=str(IMGDIR), imgsz=IMGSZ, conf=CONF,
                       device=0, half=True, stream=True, verbose=False):
    if r.boxes is None:
        continue
    # best conf of each class present in this image
    best = {}
    for b in r.boxes:
        c = int(b.cls); best[c] = max(best.get(c, 0.0), float(b.conf))
    for c, s in best.items():
        per_class[c].append((s, r.path))

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
picked = set()
for c in range(len(names)):
    for s, p in sorted(per_class.get(c, []), key=lambda x: -x[0])[:PERCLASS]:
        if p in picked:
            continue
        picked.add(p)
        shutil.copy(p, OUT / Path(p).name)
print(f"copied {len(picked)} unique candidates covering {len(per_class)} classes to {OUT}", flush=True)
