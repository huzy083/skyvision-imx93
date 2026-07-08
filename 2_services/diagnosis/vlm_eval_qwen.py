"""InsPLAD 缺陷诊断 — Qwen-VL zero-shot 评测 (命门验证).

对 supervised fault 子集 val,用 qwen-vl-max 做缺陷判别,算 per-部件 准确率/macro-F1。
key 从项目根 .env 读 (DASHSCOPE_API_KEY)。
"""
import base64
import glob
import json
import os
import random
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

from openai import OpenAI
from sklearn.metrics import accuracy_score, f1_score

ROOT = "/home/shing/uav_ground_station"
FAULT = f"{ROOT}/datasets/insplad/fault/defect_supervised"
N_PER_CLASS = 20          # 每标签抽样数 (PoC 控成本)
MODEL = "qwen-vl-max"
random.seed(42)

KEY = next(l.split("=", 1)[1].strip() for l in open(f"{ROOT}/.env")
           if l.startswith("DASHSCOPE_API_KEY="))
client = OpenAI(api_key=KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

# 标签语义词典(标签即 val 子目录名,各部件动态发现)。
SEM = {"good": "正常", "normal": "正常", "rust": "锈蚀",
       "missing-cap": "绝缘子盘缺失/掉串", "bird-nest": "鸟巢", "corrosão": "腐蚀"}
PARTS = ["glass-insulator", "lightning-rod-suspension",
         "polymer-insulator-upper-shackle", "vari-grip", "yoke-suspension"]


def labels_of(part):
    subs = sorted(d for d in os.listdir(f"{FAULT}/{part}/val")
                  if os.path.isdir(f"{FAULT}/{part}/val/{d}"))
    return {d: SEM.get(d, d) for d in subs}


def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()


def classify(part, labels, img):
    opts = "\n".join(f'- "{k}": {v}' for k, v in labels.items())
    prompt = (f"这是输电线路金具/绝缘子部件「{part}」的航拍裁剪图。"
              f"从以下候选状态里选出最符合的一个,只输出 JSON {{\"label\": \"标签\"}}:\n{opts}")
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64(img)}"}},
                    {"type": "text", "text": prompt}]}],
                max_tokens=50, temperature=0)
            txt = r.choices[0].message.content
            s = txt[txt.find("{"):txt.rfind("}") + 1]
            return json.loads(s)["label"]
        except Exception as e:
            if attempt == 2:
                return f"__err__{type(e).__name__}"
    return "__err__"


def eval_part(part, labels):
    samples = []  # (img, true_label)
    for lab in labels:
        imgs = glob.glob(f"{FAULT}/{part}/val/{lab}/*.jpg")
        random.shuffle(imgs)
        samples += [(p, lab) for p in imgs[:N_PER_CLASS]]
    with ThreadPoolExecutor(max_workers=4) as ex:
        preds = list(ex.map(lambda s: classify(part, labels, s[0]), samples))
    y_true = [s[1] for s in samples]
    valid = [(t, p) for t, p in zip(y_true, preds) if not p.startswith("__err__")]
    yt, yp = [t for t, _ in valid], [p for _, p in valid]
    acc = accuracy_score(yt, yp)
    f1 = f1_score(yt, yp, labels=list(labels), average="macro", zero_division=0)
    return acc, f1, len(samples), len(samples) - len(valid)


if __name__ == "__main__":
    import sys
    parts = sys.argv[1:] or PARTS  # 可只跑指定部件
    print(f"{'部件':32} {'样本':>5} {'准确率':>7} {'macroF1':>8} {'失败':>5}")
    accs, f1s = [], []
    for part in parts:
        acc, f1, n, err = eval_part(part, labels_of(part))
        accs.append(acc); f1s.append(f1)
        print(f"{part:32} {n:5d} {acc:7.3f} {f1:8.3f} {err:5d}")
    print(f"{'平均':32} {'':>5} {sum(accs)/len(accs):7.3f} {sum(f1s)/len(f1s):8.3f}")
