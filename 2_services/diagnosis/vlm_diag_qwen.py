"""InsPLAD 缺陷诊断 — Qwen-VL zero-shot vs few-shot,带漏报/误报分析 + 诊断文本.

用法: python vlm_diag_qwen.py [--shots 0,2] [part ...]
默认对弱项 glass-insulator / vari-grip 跑 0-shot 和 2-shot 对比。
key 从项目根 .env 读。结果存 skyvision/diagnosis/results/。
"""
import base64, glob, json, os, random, sys
from concurrent.futures import ThreadPoolExecutor

from openai import OpenAI
from sklearn.metrics import accuracy_score, f1_score

ROOT = "/home/shing/uav_ground_station"
FAULT = f"{ROOT}/datasets/insplad/fault/defect_supervised"
OUT = f"{ROOT}/skyvision/diagnosis/results"
N_PER_CLASS = 15
MODEL = "qwen-vl-max"
random.seed(42)
os.makedirs(OUT, exist_ok=True)

KEY = next(l.split("=", 1)[1].strip() for l in open(f"{ROOT}/.env")
           if l.startswith("DASHSCOPE_API_KEY="))
client = OpenAI(api_key=KEY, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

SEM = {"good": "正常", "normal": "正常", "rust": "锈蚀",
       "missing-cap": "绝缘子盘缺失/掉串", "bird-nest": "鸟巢", "corrosão": "腐蚀"}
NORMAL = {"good", "normal"}


def b64(p):
    return base64.b64encode(open(p, "rb").read()).decode()


def img_blk(p):
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64(p)}"}}


def labels_of(part):
    subs = sorted(d for d in os.listdir(f"{FAULT}/{part}/val")
                  if os.path.isdir(f"{FAULT}/{part}/val/{d}"))
    return {d: SEM.get(d, d) for d in subs}


def refs_of(part, labels, shots):
    r = {}
    for lab in labels:
        imgs = sorted(glob.glob(f"{FAULT}/{part}/train/{lab}/*.jpg"))
        random.Random(1).shuffle(imgs)
        r[lab] = imgs[:shots]
    return r


def classify(part, labels, img, refs):
    opts = "\n".join(f'- "{k}": {v}' for k, v in labels.items())
    content = []
    if refs:  # few-shot 参考图
        content.append({"type": "text", "text": f"以下是「{part}」各状态的参考样例:"})
        for lab, ps in refs.items():
            for p in ps:
                content.append(img_blk(p))
                content.append({"type": "text", "text": f'↑ 状态「{lab}」({labels[lab]})'})
        content.append({"type": "text", "text": "现在判断下面这张待检图:"})
    content.append(img_blk(img))
    content.append({"type": "text", "text":
        f'这是输电线路部件「{part}」。从候选状态选最符合的一个,'
        f'输出 JSON {{"label":"标签","reason":"一句中文依据"}}:\n{opts}'})
    for _ in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL, messages=[{"role": "user", "content": content}],
                max_tokens=120, temperature=0)
            t = r.choices[0].message.content
            d = json.loads(t[t.find("{"):t.rfind("}") + 1])
            return d.get("label", "__parse__"), d.get("reason", "")
        except Exception as e:
            err = f"__err__{type(e).__name__}"
    return err, ""


def run(part, shots):
    labels = labels_of(part)
    refs = refs_of(part, labels, shots) if shots else None
    samples = []
    for lab in labels:
        imgs = glob.glob(f"{FAULT}/{part}/val/{lab}/*.jpg")
        random.Random(42).shuffle(imgs)
        samples += [(p, lab) for p in imgs[:N_PER_CLASS]]
    with ThreadPoolExecutor(max_workers=4) as ex:
        res = list(ex.map(lambda s: classify(part, labels, s[0], refs), samples))
    rows = [{"img": os.path.basename(s[0]), "true": s[1], "pred": p, "reason": rs}
            for s, (p, rs) in zip(samples, res)]
    json.dump(rows, open(f"{OUT}/{part}_{shots}shot.json", "w"), ensure_ascii=False, indent=1)
    valid = [r for r in rows if not r["pred"].startswith("__")]
    yt = [r["true"] for r in valid]; yp = [r["pred"] for r in valid]
    acc = accuracy_score(yt, yp) if valid else 0
    f1 = f1_score(yt, yp, labels=list(labels), average="macro", zero_division=0) if valid else 0
    # 漏报: 真有缺陷却判正常 ; 误报: 真正常却判缺陷
    defects = [r for r in valid if r["true"] not in NORMAL]
    normals = [r for r in valid if r["true"] in NORMAL]
    miss = sum(1 for r in defects if r["pred"] in NORMAL)
    fp = sum(1 for r in normals if r["pred"] not in NORMAL)
    return {"acc": acc, "f1": f1, "n": len(valid),
            "miss": miss, "nd": len(defects), "fp": fp, "nn": len(normals), "rows": rows}


if __name__ == "__main__":
    args = sys.argv[1:]
    shots_list = [0, 2]
    if "--shots" in args:
        i = args.index("--shots"); shots_list = [int(x) for x in args[i + 1].split(",")]; del args[i:i + 2]
    parts = args or ["glass-insulator", "vari-grip"]
    print(f"{'部件':18} {'模式':6} {'准确率':>7} {'F1':>6} {'漏报':>10} {'误报':>10}")
    out = {}
    for part in parts:
        for sh in shots_list:
            r = run(part, sh)
            out[(part, sh)] = r
            print(f"{part:18} {sh}-shot {r['acc']:7.3f} {r['f1']:6.3f} "
                  f"{r['miss']:>3}/{r['nd']:<3}漏     {r['fp']:>3}/{r['nn']:<3}误")
    # 诊断文本样例
    print("\n=== 诊断文本样例(few-shot) ===")
    for part in parts:
        rows = out[(part, shots_list[-1])]["rows"]
        for r in rows[:2] + rows[-2:]:
            mark = "✓" if r["pred"] == r["true"] else "✗"
            print(f"[{mark}] {part} 真={r['true']} 判={r['pred']}: {r['reason']}")
