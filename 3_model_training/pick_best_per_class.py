#!/usr/bin/env python3
"""Run the deployed power model over the training set, and for each class copy
the few highest-confidence annotated images to the Desktop for a quick look."""
import shutil
from pathlib import Path
from collections import defaultdict
from ultralytics import YOLO
import cv2

MODEL  = "/home/shing/uav_ground_station/runs/insplad/yolov8n_power_merged/weights/best.pt"
IMGDIR = Path("/home/shing/uav_ground_station/datasets/insplad/det/images/train")
OUT    = Path.home() / "Desktop" / "power_model_demo"
IMGSZ, CONF, TOPN = 320, 0.35, 4   # 320 = board resolution

model = YOLO(MODEL)
names = model.names
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)

# pass 1: scan all images, collect (conf, path) per class
per_class = defaultdict(list)
n = 0
for r in model.predict(source=str(IMGDIR), imgsz=IMGSZ, conf=CONF,
                       device=0, half=True, stream=True, verbose=False):
    n += 1
    if r.boxes is None:
        continue
    for b in r.boxes:
        per_class[int(b.cls)].append((float(b.conf), r.path))
print(f"scanned {n} images", flush=True)

# pick top-N unique images per class by confidence
picks = {}
for c in range(len(names)):
    seen = []
    for conf, p in sorted(per_class.get(c, []), key=lambda x: -x[0]):
        if p in seen:
            continue
        seen.append(p)
        if len(seen) >= TOPN:
            break
    picks[c] = seen

# pass 2: re-predict the picks and save annotated crops per class
print("=== per-class ===", flush=True)
for c in range(len(names)):
    safe = f"{c:02d}_{names[c].replace(' ', '_')}"
    paths = picks[c]
    if not paths:
        print(f"{safe}: 0 (no det >= {CONF})", flush=True)
        continue
    cdir = OUT / safe
    cdir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(paths):
        r = model.predict(source=p, imgsz=IMGSZ, conf=CONF, device=0, verbose=False)[0]
        cconf = max((float(b.conf) for b in r.boxes if int(b.cls) == c), default=0.0)
        cv2.imwrite(str(cdir / f"{i+1}_conf{cconf:.2f}.jpg"), r.plot())
    top = max(x[0] for x in per_class[c])
    print(f"{safe}: {len(paths)} imgs, best conf {top:.2f}", flush=True)

print("OUT:", OUT, flush=True)
