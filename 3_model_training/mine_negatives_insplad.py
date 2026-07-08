"""挖 COCO val2017 + train2017 当 InsPLAD 负样本（COCO 没电力部件，全部可用）。

输出：图片 → datasets/insplad/det/images/train/neg_<N>.jpg
        空 label → datasets/insplad/det/labels/train/neg_<N>.txt
"""
import json, os, random, sys, urllib.request, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

random.seed(42)

N_NEG = 5000
TRAIN_IMG = Path("/home/shing/uav_ground_station/datasets/insplad/det/images/train")
TRAIN_LBL = Path("/home/shing/uav_ground_station/datasets/insplad/det/labels/train")
CACHE = Path("/tmp/coco_neg_insplad_cache")
CACHE.mkdir(parents=True, exist_ok=True)
ANN_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
ann_zip = CACHE / "annotations_trainval2017.zip"
ann_json_val = CACHE / "annotations" / "instances_val2017.json"
ann_json_train = CACHE / "annotations" / "instances_train2017.json"

# 1. download + unzip annotations if needed
if not ann_json_val.exists() or not ann_json_train.exists():
    if not ann_zip.exists():
        print(f"downloading {ANN_URL} (~242MB) ...", flush=True)
        urllib.request.urlretrieve(ANN_URL, ann_zip)
    print("unzipping annotations...", flush=True)
    with zipfile.ZipFile(ann_zip) as z:
        for n in z.namelist():
            if n.endswith(("instances_val2017.json", "instances_train2017.json")):
                z.extract(n, CACHE)

# 2. collect image_id → file_name from both splits
all_imgs = {}
for jf in (ann_json_val, ann_json_train):
    print(f"loading {jf.name}", flush=True)
    with open(jf) as f:
        d = json.load(f)
    split = "val2017" if "val" in jf.name else "train2017"
    for im in d["images"]:
        all_imgs[(split, im["id"])] = im["file_name"]

print(f"total COCO images available: {len(all_imgs)}", flush=True)

# 3. random sample
keys = list(all_imgs.keys())
random.shuffle(keys)
selected = keys[:N_NEG]
print(f"selected {len(selected)} for negatives", flush=True)


def download_one(item):
    idx, (split, img_id), fname = item
    out_img = TRAIN_IMG / f"neg_{idx:05d}.jpg"
    out_lbl = TRAIN_LBL / f"neg_{idx:05d}.txt"
    if out_img.exists() and out_lbl.exists():
        return "skip"
    url = f"http://images.cocodataset.org/{split}/{fname}"
    try:
        urllib.request.urlretrieve(url, out_img)
        out_lbl.write_text("")
        return "ok"
    except Exception as e:
        return f"err:{type(e).__name__}"


tasks = [(i, k, all_imgs[k]) for i, k in enumerate(selected)]
ok = err = skip = 0
with ThreadPoolExecutor(max_workers=16) as ex:
    for fut in as_completed(ex.submit(download_one, t) for t in tasks):
        r = fut.result()
        if r == "ok":
            ok += 1
            if ok % 200 == 0:
                print(f"  downloaded {ok}", flush=True)
        elif r == "skip":
            skip += 1
        else:
            err += 1

print(f"done. ok={ok} skip={skip} err={err}", flush=True)
