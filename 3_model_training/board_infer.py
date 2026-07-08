#!/usr/bin/env python3
"""Run the on-board Vela (Ethos-U NPU) power model over /tmp/board_test_imgs,
replicating the C++ Detector post-process exactly, and save annotated images."""
import glob, os, colorsys, sys
import numpy as np
import cv2
from tflite_runtime.interpreter import Interpreter, load_delegate

MODEL    = "/usr/bin/eiq-examples-git/models/yolov8n_power_vela.tflite"
DELEGATE = "/usr/lib/libethosu_delegate.so"
IMGDIR = sys.argv[1] if len(sys.argv) > 1 else "/tmp/board_test_imgs"
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else "/tmp/board_results"
CONF_TH, IOU_TH = 0.6, 0.5      # DETECTION_SCORE_THRESHOLD / NMS_IOU_THRESHOLD
LABELS = ["yoke", "yoke suspension", "spacer", "stockbridge damper",
          "lightning rod shackle", "lightning rod suspension",
          "polymer insulator", "glass insulator", "tower id plate", "vari-grip",
          "polymer insulator lower shackle", "polymer insulator upper shackle",
          "polymer insulator tower shackle", "glass insulator shackle",
          "spiral damper", "sphere"]
NCLS = len(LABELS)

os.makedirs(OUTDIR, exist_ok=True)
interp = Interpreter(model_path=MODEL,
                     experimental_delegates=[load_delegate(DELEGATE)])
interp.allocate_tensors()
inp, out = interp.get_input_details()[0], interp.get_output_details()[0]
inH, inW = int(inp["shape"][1]), int(inp["shape"][2])
o_scale, o_zp = out["quantization"]
print(f"model in {inW}x{inH}, out shape {list(out['shape'])} scale={o_scale:.6f} zp={o_zp}", flush=True)

def iou(a, b):
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0

def color(c):
    r, g, b = colorsys.hsv_to_rgb((c * 0.61803) % 1.0, 0.75, 1.0)
    return (int(b*255), int(g*255), int(r*255))

total = 0
for path in sorted(glob.glob(os.path.join(IMGDIR, "*"))):
    orig = cv2.imread(path)
    if orig is None:
        continue
    H0, W0 = orig.shape[:2]
    rz = cv2.resize(orig, (inW, inH))
    rgb = cv2.cvtColor(rz, cv2.COLOR_BGR2RGB).astype(np.int16)
    x = (rgb - 128).astype(np.int8)[None, ...]          # RGB int8 = pixel-128
    interp.set_tensor(inp["index"], x)
    interp.invoke()
    raw = interp.get_tensor(out["index"])[0].astype(np.float32)
    # want channel-major (4+NCLS, A); transpose if it came as (A, 4+NCLS)
    if raw.shape[0] != 4 + NCLS and raw.shape[1] == 4 + NCLS:
        raw = raw.T
    deq = (raw - o_zp) * o_scale
    cls = deq[4:4+NCLS, :]
    best_c, best_s = cls.argmax(0), cls.max(0)
    cands = []
    for a in np.nonzero(best_s > CONF_TH)[0]:
        cx, cy, w, h = deq[0, a], deq[1, a], deq[2, a], deq[3, a]
        cands.append([cx-w/2, cy-h/2, cx+w/2, cy+h/2, float(best_s[a]), int(best_c[a])])
    cands.sort(key=lambda z: -z[4])
    removed = [False] * len(cands)
    for i in range(len(cands)):
        if removed[i]:
            continue
        for j in range(i+1, len(cands)):
            if not removed[j] and iou(cands[i], cands[j]) > IOU_TH:
                removed[j] = True
    dets = [c for i, c in enumerate(cands) if not removed[i]]
    for x0, y0, x1, y1, s, c in dets:
        print(f"DET\t{os.path.basename(path)}\t{c}\t{s:.3f}", flush=True)
        p = (int(np.clip(x0,0,1)*W0), int(np.clip(y0,0,1)*H0),
             int(np.clip(x1,0,1)*W0), int(np.clip(y1,0,1)*H0))
        col = color(c)
        cv2.rectangle(orig, p[:2], p[2:], col, 2)
        cv2.putText(orig, f"{LABELS[c]} {s:.2f}", (p[0], max(12, p[1]-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)
    cv2.imwrite(os.path.join(OUTDIR, os.path.basename(path)), orig)
    total += len(dets)
    score = sum(d[4] for d in dets)   # sum of confidences = recognition richness
    print(f"SCORE\t{os.path.basename(path)}\t{score:.3f}\t{len(dets)}", flush=True)
print(f"done. {total} dets total -> {OUTDIR}", flush=True)
