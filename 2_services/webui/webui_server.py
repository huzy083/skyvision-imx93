#!/usr/bin/env python3
"""SkyVision WebUI — lightweight phone-friendly remote monitor.

Architecture:
    Phones / laptops --- HTTP --- this script ---- MQTT --- cloud broker
                          (LAN 192.168.10.x)         (mlan0 → internet)

Routes:
    GET /                  → static SPA (index.html)
    GET /static/*          → CSS / JS assets
    GET /events            → SSE stream of MQTT messages (detection, event, status, uav/pose)
    GET /api/snapshot.jpg  → latest video frame (written by skyvision_ui.py)
    GET /api/state         → current cached state JSON

Pure stdlib + paho-mqtt only.  Binds 0.0.0.0:8080 by default.
"""
import os
import sys
import json
import time
import queue
import socket
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt

# ---------------- config ----------------
HOST = "0.0.0.0"
PORT = int(os.environ.get("SKYVISION_WEBUI_PORT", "8080"))

MQTT_HOST = os.environ.get("SKYVISION_MQTT_HOST", "47.117.14.74")
MQTT_PORT = int(os.environ.get("SKYVISION_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("SKYVISION_MQTT_USER", "skyvision")
MQTT_PASS = os.environ.get("SKYVISION_MQTT_PASS", "")

STATIC_DIR = Path(__file__).resolve().parent / "static"
SNAPSHOT_PATH = Path("/tmp/skyvision-snapshot.jpg")

# topics to forward; first capture is dispatched to per-topic state slot
TOPICS = ["skyvision/detection", "skyvision/event", "skyvision/status"]
# 无人机状态走板子本地 mosquitto(uavstate经wfb/LAN发到本地broker), 不在云上
LOCAL_MQTT_HOST = os.environ.get("SKYVISION_LOCAL_MQTT_HOST", "127.0.0.1")
LOCAL_TOPICS = ["skyvision/uav_pose"]
ALL_TOPICS = TOPICS + LOCAL_TOPICS


class State:
    """Shared cached state plus pub/sub event broadcaster (SSE)."""
    def __init__(self):
        self.lock = threading.Lock()
        # last value per topic
        self.last = {t: None for t in ALL_TOPICS}
        # event log (most recent 50)
        self.events = []
        # subscribers: list of thread-safe queues
        self.subs = []
        self.subs_lock = threading.Lock()

    def update(self, topic: str, payload: dict):
        ts_recv = time.time()
        with self.lock:
            self.last[topic] = payload
            if topic == "skyvision/event":
                self.events.insert(0, payload)
                del self.events[50:]
        # broadcast to SSE subscribers
        msg = json.dumps({"topic": topic, "ts_recv": ts_recv, "data": payload})
        with self.subs_lock:
            dead = []
            for q in self.subs:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self.subs.remove(q)

    def subscribe(self) -> queue.Queue:
        q = queue.Queue(maxsize=64)
        with self.subs_lock:
            self.subs.append(q)
        # send a hello snapshot of state
        with self.lock:
            init = json.dumps({"topic": "_init", "data": {
                "last": self.last, "events": self.events}})
        try:
            q.put_nowait(init)
        except queue.Full:
            pass
        return q

    def unsubscribe(self, q: queue.Queue):
        with self.subs_lock:
            if q in self.subs:
                self.subs.remove(q)


STATE = State()


# ---------------- MQTT subscriber ----------------
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[MQTT] connect rc={reason_code}", file=sys.stderr)
    if reason_code == 0:
        for t in TOPICS:
            client.subscribe(t)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
    except Exception:
        payload = {"raw": msg.payload.decode("utf-8", errors="replace")}
    STATE.update(msg.topic, payload)


def start_mqtt():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"skyvision-webui-{os.getpid()}")
    except AttributeError:
        client = mqtt.Client(client_id=f"skyvision-webui-{os.getpid()}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS or None)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        client.loop_start()
        print(f"[MQTT] connecting {MQTT_HOST}:{MQTT_PORT}", file=sys.stderr)
    except Exception as e:
        print(f"[MQTT] init fail: {e}", file=sys.stderr)


def start_local_mqtt():
    """本地 mosquitto(无鉴权)一路: skyvision/uav_pose(uavstate遥测)."""
    def on_conn(client, userdata, flags, reason_code, properties=None):
        print(f"[MQTT-local] connect rc={reason_code}", file=sys.stderr)
        for t in LOCAL_TOPICS:
            client.subscribe(t)
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"skyvision-webui-local-{os.getpid()}")
    except AttributeError:
        client = mqtt.Client(client_id=f"skyvision-webui-local-{os.getpid()}")
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_connect = on_conn
    client.on_message = on_message
    try:
        client.connect_async(LOCAL_MQTT_HOST, 1883, keepalive=30)
        client.loop_start()
        print(f"[MQTT-local] connecting {LOCAL_MQTT_HOST}:1883", file=sys.stderr)
    except Exception as e:
        print(f"[MQTT-local] init fail: {e}", file=sys.stderr)


# ---------------- HTTP handler ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "SkyVisionWebUI/0.1"

    def log_message(self, *a, **kw):
        return  # quiet

    def _send_file(self, path: Path, ctype: str):
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # Captive-portal detection probes from various OSes — return 302
        # so iOS / Android / Win pop up the "Sign in to network" auto-browser
        # which immediately lands on our WebUI.
        host = self.headers.get("Host", "")
        path_raw = self.path
        portal_probe_hosts = (
            "captive.apple.com", "www.apple.com",                    # iOS / macOS
            "connectivitycheck.gstatic.com",                         # Android (Google)
            "connectivitycheck.platform.hicloud.com",                # Huawei
            "connect.rom.miui.com",                                  # MIUI / Xiaomi
            "wifi.vivo.com.cn",                                      # Vivo
            "www.msftconnecttest.com", "www.msftncsi.com",           # Windows
            "detectportal.firefox.com",                              # Firefox
        )
        if any(h in host for h in portal_probe_hosts):
            self._redirect_to_portal()
            return
        # Some Android variants check by path on any host
        portal_probe_paths = ("/generate_204", "/gen_204",
                              "/connecttest.txt", "/ncsi.txt",
                              "/hotspot-detect.html")
        if any(p in path_raw for p in portal_probe_paths):
            self._redirect_to_portal()
            return

        path = path_raw.split("?", 1)[0]
        if path == "/":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/static/style.css":
            self._send_file(STATIC_DIR / "style.css", "text/css")
        elif path == "/static/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript")
        elif path == "/api/snapshot.jpg":
            if SNAPSHOT_PATH.exists():
                self._send_file(SNAPSHOT_PATH, "image/jpeg")
            else:
                self.send_error(404, "no snapshot yet")
        elif path == "/api/mjpeg":
            self._mjpeg_loop()
        elif path == "/api/state":
            with STATE.lock:
                self._send_json({"last": STATE.last, "events": STATE.events})
        elif path == "/events":
            self._sse_loop()
        else:
            self.send_error(404, "not found")

    def _redirect_to_portal(self):
        # Always redirect captive-portal probes to our WebUI's fixed AP IP+port.
        # Phone CNA browser follows and shows the WebUI automatically.
        location = f"http://192.168.10.1:{PORT}/"
        body = ("<html><head><meta charset='utf-8'><title>SkyVision</title>"
                "<meta http-equiv='refresh' content='0;url=" + location + "'>"
                "</head><body>Redirecting to SkyVision...</body></html>"
                ).encode("utf-8")
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _mjpeg_loop(self):
        """Stream snapshot.jpg as multipart/x-mixed-replace. Browsers render this
        in an <img> tag as a live video. ~10fps to match snapshot writer rate."""
        boundary = "skyvisionframe"
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        last_mtime = 0.0
        try:
            while True:
                try:
                    st = SNAPSHOT_PATH.stat()
                    if st.st_mtime != last_mtime:
                        last_mtime = st.st_mtime
                        data = SNAPSHOT_PATH.read_bytes()
                        hdr = (f"--{boundary}\r\n"
                               f"Content-Type: image/jpeg\r\n"
                               f"Content-Length: {len(data)}\r\n\r\n").encode()
                        self.wfile.write(hdr)
                        self.wfile.write(data)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                except FileNotFoundError:
                    pass
                time.sleep(0.05)  # poll ~20Hz, actual fps capped by writer
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _sse_loop(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = STATE.subscribe()
        last_keepalive = time.monotonic()
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    line = f"data: {msg}\n\n".encode("utf-8")
                    self.wfile.write(line)
                    self.wfile.flush()
                except queue.Empty:
                    pass
                # heartbeat every 15s to keep connection alive
                if time.monotonic() - last_keepalive > 15:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    last_keepalive = time.monotonic()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            STATE.unsubscribe(q)


def main():
    start_mqtt()
    start_local_mqtt()
    print(f"[HTTP] listening http://{HOST}:{PORT}", file=sys.stderr)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
