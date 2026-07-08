#!/usr/bin/env python3
"""i.MX93 on-board Qwen-VL defect diagnosis daemon.

Subscribes to skyvision/detection (published by the C++ UI), crops each newly
seen component ROI from the latest snapshot, asks qwen-vl-max whether it is
defective, and publishes to skyvision/diagnosis (which the C++ UI displays).
Async / deduped so the 15fps detection+video pipeline is never touched.

Also subscribes to skyvision/event: a zone_violation ("巡检锁定区" trigger)
archives the annotated snapshot to the recordings dir and fast-tracks the
offending labels past the dedup window so they are diagnosed immediately.
"""
import base64, json, os, time, threading, queue
import cv2
import paho.mqtt.client as mqtt
from openai import OpenAI

MQTT_HOST = os.environ.get("SKYVISION_MQTT_HOST", "47.117.14.74")
MQTT_PORT = int(os.environ.get("SKYVISION_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("SKYVISION_MQTT_USER", "skyvision")
MQTT_PASS = os.environ.get("SKYVISION_MQTT_PASS", "")
SNAPSHOT  = os.environ.get("SKYVISION_SNAPSHOT", "/tmp/skyvision-snapshot.jpg")
KEYFILE   = os.environ.get("SKYVISION_ENV", "/root/skyvision-diag/.env")
MODEL     = os.environ.get("SKYVISION_VLM", "qwen-vl-max")
CONF_TH   = float(os.environ.get("SKYVISION_DIAG_CONF", "0.5"))
SAMPLE_S  = float(os.environ.get("SKYVISION_DIAG_INTERVAL", "5"))
LOGFILE   = os.environ.get("SKYVISION_DIAG_LOG", "/root/skyvision-diag/diagnosis.jsonl")
RECDIR    = os.environ.get("SKYVISION_RECDIR", "/opt/skyvision/recordings")
ZONE_HOT_S = 15.0   # after a zone alert, treat these labels as priority this long


def load_key():
    if os.environ.get("DASHSCOPE_API_KEY"):
        return os.environ["DASHSCOPE_API_KEY"]
    for l in open(KEYFILE):
        if l.startswith("DASHSCOPE_API_KEY="):
            return l.split("=", 1)[1].strip()
    raise RuntimeError("no DASHSCOPE_API_KEY")


client = OpenAI(api_key=load_key(),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

work = queue.Queue(maxsize=8)
last_seen = {}
zone_hot = {}   # label -> expiry ts; set by zone_violation events


def diagnose(part, roi_b64):
    prompt = (f'这是输电线路部件「{part}」的局部巡检切图。判断它是否存在缺陷'
              f'(如锈蚀、腐蚀、破损/裂纹、部件缺失/掉串、鸟巢、异物等)。'
              f'只输出JSON: {{"is_defect": true/false, "defect_type": "缺陷类型或正常", '
              f'"reason": "一句中文依据"}}')
    r = client.chat.completions.create(
        model=MODEL, max_tokens=150, temperature=0,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{roi_b64}"}},
            {"type": "text", "text": prompt}]}])
    t = r.choices[0].message.content
    return json.loads(t[t.find("{"):t.rfind("}") + 1])


def worker(mqc):
    while True:
        part, box, zone = work.get()
        img = cv2.imread(SNAPSHOT)
        if img is None:
            continue
        H, W = img.shape[:2]
        x0, y0, x1, y1 = box
        px = (x1 - x0) * 0.15
        py = (y1 - y0) * 0.15
        cx0, cy0 = max(0, int((x0 - px) * W)), max(0, int((y0 - py) * H))
        cx1, cy1 = min(W, int((x1 + px) * W)), min(H, int((y1 + py) * H))
        roi = img[cy0:cy1, cx0:cx1]
        if roi.size == 0:
            continue
        ok, buf = cv2.imencode(".jpg", roi)
        if not ok:
            continue
        try:
            d = diagnose(part, base64.b64encode(buf).decode())
        except Exception as e:
            print("diag err:", type(e).__name__, e, flush=True)
            continue
        out = {"part": part, "is_defect": bool(d.get("is_defect", False)),
               "defect_type": d.get("defect_type", ""), "reason": d.get("reason", ""),
               "bbox": box, "zone": zone, "ts": time.time()}
        mqc.publish("skyvision/diagnosis", json.dumps(out, ensure_ascii=False))
        try:
            with open(LOGFILE, "a") as f:
                rec = dict(out, iso=time.strftime("%Y-%m-%d %H:%M:%S",
                                                  time.localtime(out["ts"])))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            print("log err:", e, flush=True)
        print("diagnosed:", part, "defect" if out["is_defect"] else "ok",
              out["defect_type"], "|", out["reason"], flush=True)


def on_zone_violation(d):
    """巡检锁定区触发: 归档带标注快照 + 让入区类别跳过去重立即诊断."""
    labels = d.get("labels") or []
    now = time.time()
    snap = ""
    try:
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        snap = os.path.join(RECDIR, f"alert_{ts}.jpg")
        with open(SNAPSHOT, "rb") as fi, open(snap, "wb") as fo:
            fo.write(fi.read())
    except Exception as e:
        snap = ""
        print("alert snapshot err:", type(e).__name__, e, flush=True)
    for l in labels:
        zone_hot[l] = now + ZONE_HOT_S
        for k in [k for k in last_seen if k.startswith(l + ":")]:
            del last_seen[k]
    rec = {"type": "zone_alert", "labels": labels, "snapshot": snap, "ts": now,
           "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))}
    try:
        with open(LOGFILE, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        print("log err:", e, flush=True)
    print("zone alert:", ",".join(labels), "->", snap or "(no snapshot)", flush=True)


def on_message(c, u, msg):
    try:
        d = json.loads(msg.payload)
    except Exception:
        return
    if msg.topic == "skyvision/event":
        if d.get("msg") == "zone_violation":
            on_zone_violation(d)
        return
    now = time.time()
    for o in d.get("objects", []):
        label, box = o.get("label", ""), o.get("bbox")
        if not box or o.get("score", 1.0) < CONF_TH:
            continue
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        key = f"{label}:{int(cx * 10)}:{int(cy * 10)}"   # class + coarse cell
        if now - last_seen.get(key, 0) < SAMPLE_S:
            continue
        last_seen[key] = now
        zone = bool(o.get("in_zone")) or now < zone_hot.get(label, 0)
        try:
            work.put_nowait((label, box, zone))
        except queue.Full:
            pass


def on_connect(c, u, flags, rc):
    # (re)subscribe here so subscriptions survive broker restarts/reconnects
    c.subscribe("skyvision/detection")
    c.subscribe("skyvision/event")
    print(f"mqtt connected rc={rc}, subscribed", flush=True)


def main():
    mqc = mqtt.Client()
    mqc.username_pw_set(MQTT_USER, MQTT_PASS)
    mqc.on_message = on_message
    mqc.on_connect = on_connect
    while True:  # broker may be unreachable (firewalled 1883) — retry, don't crash
        try:
            mqc.connect(MQTT_HOST, MQTT_PORT, 30)
            break
        except Exception as e:
            print("broker retry:", type(e).__name__, flush=True)
            time.sleep(10)
    threading.Thread(target=worker, args=(mqc,), daemon=True).start()
    print(f"skyvision-diag up: {MODEL} conf>={CONF_TH} interval={SAMPLE_S}s", flush=True)
    mqc.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
