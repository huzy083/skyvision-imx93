"""Download COCO val2017 images that contain NO animals, use as negative samples.

Animals excluded (COCO category ids): bird 16, cat 17, dog 18, horse 19, sheep 20,
cow 21, elephant 22, bear 23, zebra 24, giraffe 25.

After this, ~500 selected images land in train/VOCdevkit/train/images/ with empty
.txt labels in train/VOCdevkit/train/labels/.
"""
import json, os, random, sys, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

random.seed(42)

ANIMAL_IDS = {16, 17, 18, 19, 20, 21, 22, 23, 24, 25}
N_NEGATIVES = 500
ANN_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
TRAIN_IMG_DIR = Path("/home/shing/uav_ground_station/rkopt/data/VOCdevkit/train/images")
TRAIN_LBL_DIR = Path("/home/shing/uav_ground_station/rkopt/data/VOCdevkit/train/labels")
CACHE_DIR = Path("/tmp/coco_neg_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ann_zip = CACHE_DIR / "annotations_trainval2017.zip"
ann_json = CACHE_DIR / "annotations" / "instances_val2017.json"

if not ann_json.exists():
    if not ann_zip.exists():
        print(f"downloading {ANN_URL} (~242MB) ...")
        urllib.request.urlretrieve(ANN_URL, ann_zip)
        print("done")
    import zipfile
    print("unzipping...")
    with zipfile.ZipFile(ann_zip) as z:
        for n in z.namelist():
            if "instances_val2017.json" in n:
                z.extract(n, CACHE_DIR)

print(f"loading {ann_json} ...")
with open(ann_json) as f:
    data = json.load(f)

# image_id -> set of category ids
img_cats = {}
for a in data["annotations"]:
    img_cats.setdefault(a["image_id"], set()).add(a["category_id"])

# select images with NO animal categories at all
images_by_id = {im["id"]: im for im in data["images"]}
candidates = []
for iid, info in images_by_id.items():
    cats = img_cats.get(iid, set())
    if not (cats & ANIMAL_IDS):
        candidates.append(info)

print(f"candidates without animals: {len(candidates)} / total {len(images_by_id)}")
random.shuffle(candidates)
chosen = candidates[:N_NEGATIVES]

def fetch(im):
    target = TRAIN_IMG_DIR / f"coco_neg_{im['id']:012d}.jpg"
    if target.exists():
        return
    try:
        urllib.request.urlretrieve(im["coco_url"], target)
        (TRAIN_LBL_DIR / f"coco_neg_{im['id']:012d}.txt").write_text("")
    except Exception as e:
        print(f"  failed {im['id']}: {e}", file=sys.stderr)

print(f"downloading {len(chosen)} images to {TRAIN_IMG_DIR} ...")
with ThreadPoolExecutor(max_workers=16) as ex:
    for i, _ in enumerate(ex.map(fetch, chosen), 1):
        if i % 50 == 0:
            print(f"  {i}/{len(chosen)}")

n_added = len(list(TRAIN_IMG_DIR.glob("coco_neg_*.jpg")))
print(f"done. {n_added} negatives now in train set.")
