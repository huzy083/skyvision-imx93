import json
import os
from pathlib import Path

ROOT = Path("/home/shing/uav_ground_station/datasets/insplad/det")
ANN = ROOT / "annotations"
SPLITS = {"train": "instances_train.json", "val": "instances_val.json"}

# 以 category_id 升序映射到 0..N-1
with open(ANN / SPLITS["train"]) as f:
    cats = json.load(f)["categories"]
cat_ids = sorted(c["id"] for c in cats)
id2idx = {cid: i for i, cid in enumerate(cat_ids)}
names = [next(c["name"] for c in cats if c["id"] == cid) for cid in cat_ids]
print(f"{len(names)} classes:", names)

for split, jf in SPLITS.items():
    with open(ANN / jf) as f:
        d = json.load(f)
    imgs = {im["id"]: im for im in d["images"]}
    by_img = {}
    for a in d["annotations"]:
        by_img.setdefault(a["image_id"], []).append(a)

    lbl_dir = ROOT / "labels" / split
    lbl_dir.mkdir(parents=True, exist_ok=True)
    n_box = 0
    for img_id, im in imgs.items():
        w, h = im["width"], im["height"]
        stem = Path(im["file_name"]).stem
        lines = []
        for a in by_img.get(img_id, []):
            x, y, bw, bh = a["bbox"]
            cx, cy = (x + bw / 2) / w, (y + bh / 2) / h
            lines.append(f"{id2idx[a['category_id']]} {cx:.6f} {cy:.6f} {bw/w:.6f} {bh/h:.6f}")
            n_box += 1
        (lbl_dir / f"{stem}.txt").write_text("\n".join(lines))
    print(f"{split}: {len(imgs)} imgs, {n_box} boxes -> {lbl_dir}")

# 写 data.yaml
yaml = ROOT.parent / "insplad_det.yaml"
with open(yaml, "w") as f:
    f.write(f"path: {ROOT}\n")
    f.write("train: images/train\nval: images/val\n\n")
    f.write(f"nc: {len(names)}\n")
    f.write("names:\n")
    for n in names:
        f.write(f"  - {n}\n")
print("wrote", yaml)
