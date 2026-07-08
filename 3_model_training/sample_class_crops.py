"""每个类别复制几张整图放桌面,直观查看 18 类电力部件在塔上的位置。"""
import random
import shutil
from pathlib import Path

ROOT = Path("/home/shing/uav_ground_station/datasets/insplad/det")
OUT = Path("/home/shing/Desktop/InsPLAD_类别样例")
PER_CLASS = 6
random.seed(0)

names = [
    "yoke", "yoke suspension", "spacer", "stockbridge damper",
    "lightning rod shackle", "lightning rod suspension", "polymer insulator",
    "glass insulator", "tower id plate", "vari-grip",
    "polymer insulator lower shackle", "polymer insulator upper shackle",
    "polymer insulator tower shackle", "glass insulator big shackle",
    "glass insulator small shackle", "glass insulator tower shackle",
    "spiral damper", "sphere",
]

# 收集每类包含该类的整图(去重)
inst = {i: set() for i in range(len(names))}
for split in ("train", "val"):
    lbl_dir = ROOT / "labels" / split
    img_dir = ROOT / "images" / split
    for lf in lbl_dir.glob("*.txt"):
        img = img_dir / f"{lf.stem}.jpg"
        if not img.exists():
            continue
        for line in lf.read_text().splitlines():
            if not line.strip():
                continue
            inst[int(line.split()[0])].add(img)

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
for ci, name in enumerate(names):
    items = list(inst[ci])
    random.shuffle(items)
    d = OUT / f"{ci:02d}_{name.replace(' ', '_')}"
    d.mkdir()
    picked = items[:PER_CLASS]
    for img_path in picked:
        shutil.copy(img_path, d / img_path.name)
    print(f"{ci:02d} {name}: {len(picked)}/{len(items)} 张")
print("输出:", OUT)
