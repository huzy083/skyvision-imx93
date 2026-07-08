#!/usr/bin/env python3
"""SkyVision ground station UI - dual camera + NPU object detection."""

import os
import sys
import time
import json
import threading
import subprocess
from collections import deque
from pathlib import Path

import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
from gi.repository import Gst, GstApp  # noqa: E402

import numpy as np  # noqa: E402
import cv2  # noqa: E402
import tflite_runtime.interpreter as tflite  # noqa: E402
import paho.mqtt.client as mqtt  # noqa: E402

from PySide6.QtCore import (  # noqa: E402
    QObject, Property, Signal, Slot, QTimer, QDateTime, Qt,
)
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPen, QColor, QFont  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickPaintedItem  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402



os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/0")
os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")


JITTER_BUFFER_MS = 300
DETECTION_MODEL = "/usr/bin/eiq-examples-git/models/yolov8n_skyvision_vela.tflite"
ETHOSU_DELEGATE = "/usr/lib/libethosu_delegate.so"
DETECTION_INTERVAL_FRAMES = 2
DISABLE_INFERENCE = os.environ.get("SKYVISION_DISABLE_INFERENCE", "0") == "1"
DISABLE_SNAPSHOT_STREAM = os.environ.get("SKYVISION_DISABLE_SNAPSHOT_STREAM", "0") == "1"
LOG_FPS = os.environ.get("SKYVISION_LOG_FPS", "0") == "1"
DETECTION_SCORE_THRESHOLD = 0.6
NMS_IOU_THRESHOLD = 0.5
ANIMAL_LABELS = ["elephant", "tiger", "wolf", "peacock", "monkey"]
ANIMAL_LABELS_CN = {"elephant": "大象", "tiger": "老虎", "wolf": "狼", "peacock": "孔雀", "monkey": "猴子"}

MQTT_HOST = os.environ.get("SKYVISION_MQTT_HOST", "47.117.14.74")
MQTT_PORT = int(os.environ.get("SKYVISION_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("SKYVISION_MQTT_USER", "skyvision")
MQTT_PASS = os.environ.get("SKYVISION_MQTT_PASS", "")
MQTT_TOPIC_DETECTION = "skyvision/detection"
MQTT_TOPIC_EVENT = "skyvision/event"
MQTT_TOPIC_STATUS = "skyvision/status"
MQTT_TOPIC_LINK = "skyvision/link_stats"
MQTT_TOPIC_DIAGNOSIS = "skyvision/diagnosis"
MQTT_DETECTION_INTERVAL_S = 0.5
MQTT_STATUS_INTERVAL_S = 5.0

RECORDINGS_DIR = Path(os.environ.get("SKYVISION_RECORDINGS_DIR",
                                     "/opt/skyvision/recordings"))
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

CAMERAS = {
    "forward": {"name": "前视", "port": 5000},
    "down":    {"name": "下视", "port": 5001},
}


def make_pipeline(port: int) -> str:
    # tee0: raw H.264 -> record valve+appsink, decoded display, inference (all PXP HW)
    pipeline = (
        f'udpsrc port={port} buffer-size=32768 '
        'caps="application/x-rtp,media=video,clock-rate=90000,encoding-name=H264,payload=96" ! '
        f'rtpjitterbuffer name=jb latency={JITTER_BUFFER_MS} do-lost=false drop-on-latency=false ! '
        'rtph264depay ! h264parse config-interval=-1 ! '
        'tee name=raw_t '
        # record branch: gated by valve; appsink hands raw H.264 NALs to Python
        'raw_t. ! queue max-size-buffers=400 max-size-time=4000000000 max-size-bytes=0 leaky=no ! '
        'valve name=rec_valve drop=true ! '
        'video/x-h264,stream-format=byte-stream,alignment=au ! '
        'appsink name=recsink emit-signals=true max-buffers=10 drop=true sync=false async=false '
        # decode branch: feeds the existing display+inference tee
        'raw_t. ! queue max-size-buffers=1 leaky=downstream ! '
        'avdec_h264 max-threads=2 thread-type=2 output-corrupt=true ! '
        'tee name=t '
        # display branch
        't. ! queue max-size-buffers=1 leaky=downstream ! '
        'imxvideoconvert_pxp ! '
        'video/x-raw,format=BGRx ! '
        'appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false '
    )
    if not DISABLE_INFERENCE:
        pipeline += (
            # inference branch: HW-resized BGR 320x320 for YOLOv8n NPU model
            't. ! queue max-size-buffers=1 leaky=downstream ! '
            'imxvideoconvert_pxp ! '
            'video/x-raw,format=BGR,width=320,height=320 ! '
            'appsink name=infsink emit-signals=true max-buffers=1 drop=true sync=false'
        )
    return pipeline


def make_playback_pipeline(path: Path) -> str:
    """Build a file -> decode -> PXP -> appsink pipeline for recorded playback.
    Supports both MP4 (via qtdemux) and raw H.264 annex-B (via h264parse)."""
    p = str(path)
    if p.endswith(".mp4"):
        src = f'filesrc location="{p}" ! qtdemux ! h264parse '
    else:
        src = f'filesrc location="{p}" ! h264parse '
    return (
        src + '! '
        'avdec_h264 max-threads=2 thread-type=2 output-corrupt=true ! '
        'imxvideoconvert_pxp ! '
        'video/x-raw,format=BGRx,width=960,height=600 ! '
        'appsink name=sink emit-signals=true max-buffers=2 drop=false sync=true'
    )


class Detector:
    """YOLOv8n int8 (Vela-compiled) + Ethos-U65 NPU. Custom 5-class animal model.

    Input:  (1, 320, 320, 3) int8, scale ~1/255, zero_point=-128 (uint8 RGB -> int8 = -128)
    Output: (1, 9, 2100) int8 — 4 box (xywh center, in pixel coords 0..320) + 5 class scores
    Anchors: 2100 = 40*40 + 20*20 + 10*10 (3 detection scales)
    """
    MAX_DETS = 5

    def __init__(self):
        self._interp = tflite.Interpreter(
            model_path=DETECTION_MODEL,
            experimental_delegates=[tflite.load_delegate(ETHOSU_DELEGATE)],
        )
        self._interp.allocate_tensors()
        inp = self._interp.get_input_details()[0]
        out = self._interp.get_output_details()[0]
        self._in_idx = inp["index"]
        self._in_h = inp["shape"][1]
        self._in_w = inp["shape"][2]
        self._in_scale, self._in_zp = inp["quantization"]
        self._out_idx = out["index"]
        self._out_scale, self._out_zp = out["quantization"]
        print(f"YOLO model loaded: in {inp['shape']} {inp['dtype']} q={inp['quantization']}, "
              f"out {out['shape']} {out['dtype']} q={out['quantization']}", file=sys.stderr)

    def infer(self, img_rgb: np.ndarray):
        """img_rgb: HxWx3 uint8 RGB at any size (will be resized).
        Returns top-K list of {x0,y0,x1,y1,label,score} normalized to [0,1]."""
        if img_rgb.shape[:2] != (self._in_h, self._in_w):
            img_rgb = cv2.resize(img_rgb, (self._in_w, self._in_h))
        # uint8 [0,255] -> int8 [-128,127]
        inp = (img_rgb.astype(np.int16) - 128).astype(np.int8)
        self._interp.set_tensor(self._in_idx, inp[None, ...])
        self._interp.invoke()
        raw = self._interp.get_tensor(self._out_idx)[0]  # (9, 2100) int8
        # Dequantize
        raw_f = (raw.astype(np.float32) - self._out_zp) * self._out_scale  # (9, 2100)
        # First 4 = box xywh (center, normalized [0,1] since ultralytics export is normalized when nms=False? Actually need to verify)
        # ultralytics yolov8 raw output: box xywh in [0, imgsz] pixel coords, scores already sigmoided (0..1)
        boxes = raw_f[:4, :]              # (4, 2100): cx, cy, w, h in pixel coords [0..320]
        scores = raw_f[4:, :]             # (5, 2100)
        cls_id = scores.argmax(axis=0)    # (2100,)
        cls_score = scores.max(axis=0)    # (2100,)
        keep = cls_score > DETECTION_SCORE_THRESHOLD
        if not np.any(keep):
            return []
        boxes = boxes[:, keep]                # (4, N)
        cls_id = cls_id[keep]                 # (N,)
        cls_score = cls_score[keep]           # (N,)
        # YOLOv8 (ultralytics nms=False export) outputs xywh ALREADY normalized [0,1]
        cx, cy, w, h = boxes
        x0 = cx - w / 2
        y0 = cy - h / 2
        x1 = cx + w / 2
        y1 = cy + h / 2
        boxes_xywh = np.stack([x0, y0, w, h], axis=1).astype(np.float32)
        idxs = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(),
            cls_score.tolist(),
            DETECTION_SCORE_THRESHOLD,
            NMS_IOU_THRESHOLD,
        )
        if len(idxs) == 0:
            return []
        idxs = np.asarray(idxs).flatten()
        # sort by score desc and cap
        idxs = idxs[np.argsort(-cls_score[idxs])][: self.MAX_DETS]
        dets = []
        for i in idxs:
            dets.append({
                "x0": float(np.clip(x0[i], 0.0, 1.0)),
                "y0": float(np.clip(y0[i], 0.0, 1.0)),
                "x1": float(np.clip(x1[i], 0.0, 1.0)),
                "y1": float(np.clip(y1[i], 0.0, 1.0)),
                "label": ANIMAL_LABELS[int(cls_id[i])],
                "score": float(cls_score[i]),
            })
        return dets


class VideoItem(QQuickPaintedItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.setFillColor(Qt.black)

    def set_image(self, img: QImage):
        self._image = img
        self.update()

    def paint(self, painter):
        if self._image.isNull():
            return
        painter.drawImage(self.boundingRect().topLeft(), self._image)


class GstRunner(QObject):
    frameReady = Signal(QImage)
    rawReady = Signal(object)  # numpy RGB ndarray (h,w,3) for NPU
    fpsChanged = Signal(float)
    bitrateChanged = Signal(float)
    latencyChanged = Signal(float)
    linkChanged = Signal(bool)

    def __init__(self, port: int, parent=None):
        super().__init__(parent)
        self._port = port
        self._frame_count = 0
        self._byte_count = 0
        self._lag_sum_ns = 0
        self._lag_n = 0
        self._last_stats_t = time.monotonic()
        self._linked = False
        self._infer_skip = 0

        self._pipeline = Gst.parse_launch(make_pipeline(port))
        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)
        infsink = self._pipeline.get_by_name("infsink")
        if infsink is not None:
            infsink.connect("new-sample", self._on_inf_sample)

        self._rec_valve = self._pipeline.get_by_name("rec_valve")
        recsink = self._pipeline.get_by_name("recsink")
        recsink.connect("new-sample", self._on_rec_sample)
        self._rec_lock = threading.Lock()
        self._rec_file = None
        self._rec_path = None
        self._rec_bytes = 0
        self._rec_start_t = 0.0

        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._tick)

    def play(self):
        self._pipeline.set_state(Gst.State.PLAYING)
        self._stats_timer.start(1000)
        self._last_stats_t = time.monotonic()
        self._frame_count = 0
        self._byte_count = 0

    def stop(self):
        self._stats_timer.stop()
        self._pipeline.set_state(Gst.State.NULL)
        if self._linked:
            self._linked = False
            self.linkChanged.emit(False)
        self.fpsChanged.emit(0.0)
        self.bitrateChanged.emit(0.0)

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        w = caps.get_value("width")
        h = caps.get_value("height")
        size = buf.get_size()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            raw_bytes = bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)

        # BGRx 4 bytes/pixel; QImage RGB32 matches BGRx memory layout on LE
        img = QImage(raw_bytes, w, h, w * 4, QImage.Format_RGB32).copy()
        self.frameReady.emit(img)

        # Detection runs via the inference branch (HW-resized 300x300 BGR via PXP tee)

        pts = buf.pts
        if pts is not None and pts != Gst.CLOCK_TIME_NONE:
            clock = self._pipeline.get_clock()
            if clock is not None:
                now_running = clock.get_time() - self._pipeline.get_base_time()
                lag_ns = now_running - pts
                if 0 < lag_ns < 10_000_000_000:
                    self._lag_sum_ns += lag_ns
                    self._lag_n += 1
        self._frame_count += 1
        self._byte_count += size
        return Gst.FlowReturn.OK

    def _on_inf_sample(self, sink):
        # Already 300x300 BGR (PXP HW resized), zero CPU work needed here
        self._infer_skip += 1
        if self._infer_skip < DETECTION_INTERVAL_FRAMES:
            sink.emit("pull-sample")  # discard to free buffer
            return Gst.FlowReturn.OK
        self._infer_skip = 0
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            raw = bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)
        # 320 is already 16-aligned. BGR -> RGB swap for YOLO model.
        side = 320
        bgr = np.frombuffer(raw, dtype=np.uint8).reshape(side, side, 3)
        rgb = bgr[:, :, ::-1].copy()
        # DEBUG: dump every 60th frame to /tmp/yolo_input_NNN.jpg for inspection
        if not hasattr(self, "_dump_n"):
            self._dump_n = 0
        self._dump_n += 1
        if self._dump_n % 60 == 0:
            try:
                cv2.imwrite(f"/tmp/yolo_input_{(self._dump_n // 60) % 5}.jpg", bgr)
            except Exception:
                pass
        self.rawReady.emit(rgb)
        return Gst.FlowReturn.OK

    def _tick(self):
        now = time.monotonic()
        dt = now - self._last_stats_t
        if dt <= 0:
            return
        fps = self._frame_count / dt
        mbps = self._byte_count * 8.0 / 1_000_000.0 / dt
        if self._lag_n > 0:
            lag_ms = (self._lag_sum_ns / self._lag_n) / 1_000_000
            self.latencyChanged.emit(JITTER_BUFFER_MS + lag_ms + 16)
            if LOG_FPS:
                print(f"[LAG] board_lag_ms={lag_ms:.0f} (jitter={JITTER_BUFFER_MS})", flush=True)
        linked = fps > 1.0
        if linked != self._linked:
            self._linked = linked
            self.linkChanged.emit(linked)
        self.fpsChanged.emit(fps)
        self.bitrateChanged.emit(mbps)
        if LOG_FPS:
            print(f"[FPS] display={fps:.2f} mbps={mbps:.2f}", flush=True)

    # ---- recording ----
    def start_recording(self, path: Path) -> bool:
        with self._rec_lock:
            if self._rec_file is not None:
                return False
            self._rec_file = open(path, "wb", buffering=64 * 1024)
            self._rec_path = path
            self._rec_bytes = 0
            self._rec_start_t = time.monotonic()
        if self._rec_valve is not None:
            self._rec_valve.set_property("drop", False)
        return True

    def stop_recording(self):
        """Close current recording. Returns (h264_path, n_bytes, duration_s) or None."""
        if self._rec_valve is not None:
            self._rec_valve.set_property("drop", True)
        with self._rec_lock:
            if self._rec_file is None:
                return None
            try:
                self._rec_file.flush()
                self._rec_file.close()
            except Exception:
                pass
            path = self._rec_path
            n = self._rec_bytes
            dur = time.monotonic() - self._rec_start_t
            self._rec_file = None
            self._rec_path = None
            self._rec_bytes = 0
        return path, n, dur

    def _on_rec_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            data = bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)
        with self._rec_lock:
            if self._rec_file is not None:
                try:
                    self._rec_file.write(data)
                    self._rec_bytes += len(data)
                except Exception as e:
                    print(f"rec write err: {e}", file=sys.stderr)
        return Gst.FlowReturn.OK


class PlaybackRunner(QObject):
    """Plays back a recorded file into the same VideoItem."""
    frameReady = Signal(QImage)
    finished = Signal()

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self._path = path
        self._pipeline = Gst.parse_launch(make_playback_pipeline(path))
        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_new_sample)
        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::eos", lambda *_: self.finished.emit())
        bus.connect("message::error",
                    lambda b, msg: (print(f"playback err: {msg.parse_error()}",
                                          file=sys.stderr), self.finished.emit()))

    def play(self):
        self._pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self._pipeline.set_state(Gst.State.NULL)

    def _on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        buf = sample.get_buffer()
        caps = sample.get_caps().get_structure(0)
        w = caps.get_value("width")
        h = caps.get_value("height")
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            raw = bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)
        img = QImage(raw, w, h, w * 4, QImage.Format_RGB32).copy()
        self.frameReady.emit(img)
        return Gst.FlowReturn.OK
        self._frame_count = 0
        self._byte_count = 0
        self._lag_sum_ns = 0
        self._lag_n = 0
        self._last_stats_t = now


class MqttPublisher:
    """Async MQTT publisher with auto-reconnect. Drops cleanly if broker unreachable."""

    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._connected = False
        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"skyvision-rx-{os.getpid()}",
            )
        except Exception as e:
            print(f"[MQTT] init failed: {e}", file=sys.stderr)
            self._client = None
            return
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        if MQTT_USER:
            self._client.username_pw_set(MQTT_USER, MQTT_PASS or None)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._link_stats_cb = None  # set externally to receive link_stats updates
        self._diagnosis_cb = None  # set externally to receive diagnosis events
        # last-will so subscribers know if we crash
        self._client.will_set(
            MQTT_TOPIC_STATUS,
            json.dumps({"ts": time.time(), "online": False}),
            qos=1, retain=True,
        )
        try:
            self._client.connect_async(host, port, keepalive=30)
            self._client.loop_start()
            print(f"[MQTT] connecting to {host}:{port}", file=sys.stderr)
        except Exception as e:
            print(f"[MQTT] connect_async failed: {e}", file=sys.stderr)
        self._last_det_pub = 0.0

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self._connected = (reason_code == 0)
        print(f"[MQTT] on_connect rc={reason_code} connected={self._connected}",
              file=sys.stderr)
        if self._connected:
            client.publish(MQTT_TOPIC_STATUS,
                json.dumps({"ts": time.time(), "online": True}),
                qos=1, retain=True)
            # subscribe to local link-analyzer feed
            client.subscribe("skyvision/link_stats")
            client.subscribe("skyvision/diagnosis")

    def _on_message(self, client, userdata, msg):
        if msg.topic == "skyvision/diagnosis" and self._diagnosis_cb is not None:
            try:
                self._diagnosis_cb(json.loads(msg.payload))
            except Exception:
                pass
            return
        if msg.topic == "skyvision/link_stats" and self._link_stats_cb is not None:
            try:
                payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
                self._link_stats_cb(payload)
            except Exception as e:
                print(f"[MQTT] link_stats decode error: {e}", file=sys.stderr)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._connected = False
        print(f"[MQTT] disconnected rc={reason_code}", file=sys.stderr)

    def publish_detection(self, camera: str, dets: list):
        if self._client is None:
            return
        now = time.monotonic()
        if now - self._last_det_pub < MQTT_DETECTION_INTERVAL_S:
            return
        self._last_det_pub = now
        payload = {
            "ts": time.time(),
            "camera": camera,
            "objects": [
                {
                    "label": d["label"],
                    "score": round(float(d["score"]), 3),
                    "bbox": [
                        round(float(d["x0"]), 3), round(float(d["y0"]), 3),
                        round(float(d["x1"]), 3), round(float(d["y1"]), 3),
                    ],
                }
                for d in dets
            ],
        }
        self._client.publish(MQTT_TOPIC_DETECTION, json.dumps(payload), qos=0)

    def publish_event(self, msg: str, level: str = "info", **extra):
        if self._client is None:
            return
        payload = {"ts": time.time(), "level": level, "msg": msg, **extra}
        self._client.publish(MQTT_TOPIC_EVENT, json.dumps(payload), qos=1)

    def publish_status(self, **stats):
        if self._client is None:
            return
        payload = {"ts": time.time(), "online": True, **stats}
        self._client.publish(MQTT_TOPIC_STATUS, json.dumps(payload),
                             qos=0, retain=True)

    def stop(self):
        if self._client is None:
            return
        try:
            self._client.publish(MQTT_TOPIC_STATUS,
                json.dumps({"ts": time.time(), "online": False}),
                qos=1, retain=True).wait_for_publish(timeout=1.0)
        except Exception:
            pass
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:
            pass


class AppController(QObject):
    statsChanged = Signal()
    clockChanged = Signal()
    recordingChanged = Signal()
    cameraChanged = Signal()
    detectionsChanged = Signal()
    playbackChanged = Signal()
    recordingsListChanged = Signal()
    event = Signal(str, str)
    diagnosisReceived = Signal(dict)
    snapshotRequested = Signal()
    recordingRequested = Signal(bool)

    @Slot(dict)
    def addDiagnosisEvent(self, payload):
        cam = payload.get('camera', '?')
        part = payload.get('part', '?')
        is_def = payload.get('is_defect', False)
        defect = payload.get('defect_type', '')
        reason = payload.get('reason', '')
        cam_cn = {'forward': '前视', 'down': '下视'}.get(cam, cam)
        if is_def:
            text = f'[{cam_cn}] {part} → 缺陷: {defect} | {reason}'
            sev = 'alert'
        else:
            text = f'[{cam_cn}] {part} 正常 | {reason}'
            sev = 'info'
        self.event.emit(text, sev)
        self.diagnosisReceived.emit(payload)
    playbackRequested = Signal(str)
    livePlaybackResumed = Signal()
    zoneChanged = Signal()
    linkStatsChanged = Signal()
    linkModeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fps = 0.0
        self._latency_ms = 0.0
        self._bitrate_mbps = 0.0
        self._link_status = "等待视频"
        self._clock_text = ""
        self._recording = False
        self._current_camera = "forward"
        self._monitor_mode = True
        self._detections = []
        self._detect_count = 0
        self._playback_mode = False
        self._playback_file = ""
        self._recordings = []
        # Zone alert state
        self._zone_polygon = []         # list of [nx, ny] in [0,1]
        self._zone_enabled = False
        self._zone_draw_mode = False
        self._zone_violation = False    # any current detection inside zone
        # Link analyzer state (from IW612 mon0 via MQTT skyvision/link_stats)
        self._link_pps = 0
        self._link_kbps = 0.0
        self._link_retry_pct = 0.0
        self._link_rssi_avg = None       # None until first sample
        self._link_rssi_min = None
        self._link_rssi_max = None
        self._link_mcs_top = -1          # most-used MCS index this second
        self._link_last_ts = 0.0

        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._on_clock_tick)
        self._clock_timer.start(1000)
        self._on_clock_tick()

    @Property(float, notify=statsChanged)
    def fps(self):
        return self._fps

    @Property(float, notify=statsChanged)
    def latencyMs(self):
        return self._latency_ms

    @Property(float, notify=statsChanged)
    def bitrateMbps(self):
        return self._bitrate_mbps

    @Property(str, notify=statsChanged)
    def linkStatus(self):
        return self._link_status

    @Property(str, notify=clockChanged)
    def clockText(self):
        return self._clock_text

    @Property(bool, notify=recordingChanged)
    def recording(self):
        return self._recording

    @recording.setter
    def recording(self, v):
        if self._recording == v:
            return
        self._recording = v
        self.recordingChanged.emit()
        self.event.emit("开始录像" if v else "停止录像", "info")

    @Property(str, notify=cameraChanged)
    def currentCamera(self):
        return self._current_camera

    @Property(str, notify=cameraChanged)
    def cameraName(self):
        return CAMERAS[self._current_camera]["name"]

    @Property(list, notify=detectionsChanged)
    def detections(self):
        return self._detections

    @Property(int, notify=detectionsChanged)
    def detectionCount(self):
        return self._detect_count

    def set_current_camera(self, cam: str):
        if cam == self._current_camera or cam not in CAMERAS:
            return
        self._current_camera = cam
        self.cameraChanged.emit()
        self.event.emit(f"切换至 {CAMERAS[cam]['name']}", "info")

    def _on_clock_tick(self):
        self._clock_text = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.clockChanged.emit()

    @Slot(float)
    def updateFps(self, fps):
        self._fps = fps
        self.statsChanged.emit()

    @Slot(float)
    def updateBitrate(self, mbps):
        self._bitrate_mbps = mbps
        self.statsChanged.emit()

    @Slot(float)
    def updateLatency(self, ms):
        self._latency_ms = ms
        self.statsChanged.emit()

    @Slot(bool)
    def updateLink(self, linked):
        self._link_status = "已连接" if linked else "等待视频"
        self.statsChanged.emit()

    def updateDetections(self, dets):
        self._detections = dets
        self._detect_count = len(dets)
        self.detectionsChanged.emit()

    @Slot()
    def snapshot(self):
        self.snapshotRequested.emit()

    @Slot()
    def toggleRecording(self):
        new_val = not self._recording
        self.recordingRequested.emit(new_val)
        # state actually set by CameraManager after pipeline succeeds

    def setRecordingState(self, v: bool):
        if self._recording == v:
            return
        self._recording = v
        self.recordingChanged.emit()
        self.event.emit("开始录像" if v else "停止录像", "info")

    @Slot()
    def openZoneAlert(self):
        self.event.emit("打开区域告警配置", "info")

    # ---- zone alert API (exposed to QML) ----
    @Property(list, notify=zoneChanged)
    def zonePolygon(self):
        return self._zone_polygon

    @Property(bool, notify=zoneChanged)
    def zoneEnabled(self):
        return self._zone_enabled

    @Property(bool, notify=zoneChanged)
    def zoneDrawMode(self):
        return self._zone_draw_mode

    @Property(bool, notify=zoneChanged)
    def zoneViolation(self):
        return self._zone_violation

    @Slot(bool)
    def setZoneEnabled(self, v: bool):
        if v == self._zone_enabled:
            return
        self._zone_enabled = v
        if v and len(self._zone_polygon) < 3:
            self.event.emit("禁区未画完整(至少3点)", "warn")
            self._zone_enabled = False
        else:
            self.event.emit("禁区告警 " + ("启用" if v else "关闭"), "info")
        self.zoneChanged.emit()

    @Slot()
    def toggleZoneDraw(self):
        self._zone_draw_mode = not self._zone_draw_mode
        if self._zone_draw_mode:
            # entering draw mode wipes the polygon and starts fresh
            self._zone_polygon = []
            self._zone_enabled = False
            self.event.emit("禁区绘制：在视频上依次点击 → 双击/右键 完成", "info")
        else:
            if len(self._zone_polygon) >= 3:
                self.event.emit(f"禁区绘制完成({len(self._zone_polygon)}点)", "info")
        self.zoneChanged.emit()

    @Slot(float, float)
    def addZoneVertex(self, nx: float, ny: float):
        if not self._zone_draw_mode:
            return
        # clamp to [0,1]
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))
        self._zone_polygon.append([nx, ny])
        self.zoneChanged.emit()

    @Slot()
    def finishZoneDraw(self):
        if self._zone_draw_mode and len(self._zone_polygon) >= 3:
            self._zone_draw_mode = False
            self._zone_enabled = True
            self.event.emit(f"禁区告警启用({len(self._zone_polygon)}点)", "info")
            self.zoneChanged.emit()

    @Slot()
    def clearZone(self):
        self._zone_polygon = []
        self._zone_enabled = False
        self._zone_draw_mode = False
        self.event.emit("禁区已清除", "info")
        self.zoneChanged.emit()

    def setZoneViolation(self, v: bool):
        if v == self._zone_violation:
            return
        self._zone_violation = v
        self.zoneChanged.emit()

    # ---- link analyzer (IW612 mon0) ----
    @Property(int, notify=linkStatsChanged)
    def linkPps(self):
        return self._link_pps

    @Property(float, notify=linkStatsChanged)
    def linkKbps(self):
        return self._link_kbps

    @Property(float, notify=linkStatsChanged)
    def linkRetryPct(self):
        return self._link_retry_pct

    @Property(int, notify=linkStatsChanged)
    def linkRssiAvg(self):
        return int(self._link_rssi_avg) if self._link_rssi_avg is not None else 0

    @Property(int, notify=linkStatsChanged)
    def linkRssiMin(self):
        return self._link_rssi_min if self._link_rssi_min is not None else 0

    @Property(int, notify=linkStatsChanged)
    def linkRssiMax(self):
        return self._link_rssi_max if self._link_rssi_max is not None else 0

    @Property(int, notify=linkStatsChanged)
    def linkMcsTop(self):
        return self._link_mcs_top

    @Property(bool, notify=linkStatsChanged)
    def linkActive(self):
        return (time.time() - self._link_last_ts) < 3.0

    def updateLinkStats(self, payload: dict):
        self._link_pps = int(payload.get("pps", 0))
        self._link_kbps = float(payload.get("kbps", 0.0))
        self._link_retry_pct = float(payload.get("retry_pct", 0.0))
        ra = payload.get("rssi_avg")
        self._link_rssi_avg = ra if ra is not None else self._link_rssi_avg
        rmn = payload.get("rssi_min")
        rmx = payload.get("rssi_max")
        self._link_rssi_min = rmn if rmn is not None else self._link_rssi_min
        self._link_rssi_max = rmx if rmx is not None else self._link_rssi_max
        hist = payload.get("mcs_hist") or {}
        if hist:
            top = max(hist.items(), key=lambda kv: kv[1])
            self._link_mcs_top = int(top[0])
        self._link_last_ts = time.time()
        self.linkStatsChanged.emit()

    @Slot()
    def switchCamera(self):
        nxt = "down" if self._current_camera == "forward" else "forward"
        self.set_current_camera(nxt)

    @Property(bool, notify=linkModeChanged)
    def monitorMode(self):
        return self._monitor_mode

    @Slot()
    def toggleLinkMode(self):
        import subprocess
        self._monitor_mode = not self._monitor_mode
        mode = "monitor" if self._monitor_mode else "wifi"
        try:
            subprocess.Popen(["/root/skyvision-wfb/switch.sh", mode])
        except Exception as e:
            print("[LINKMODE] fail:", e, flush=True)
        self.linkModeChanged.emit()

    @Property(bool, notify=playbackChanged)
    def playbackMode(self):
        return self._playback_mode

    @Property(str, notify=playbackChanged)
    def playbackFile(self):
        return self._playback_file

    @Property(list, notify=recordingsListChanged)
    def recordings(self):
        return self._recordings

    @Slot()
    def refreshRecordings(self):
        files = []
        for p in sorted(RECORDINGS_DIR.iterdir(), reverse=True):
            if p.suffix not in (".mp4", ".h264"):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            files.append({
                "name": p.name,
                "path": str(p),
                "size_mb": round(st.st_size / 1024 / 1024, 2),
                "mtime": QDateTime.fromSecsSinceEpoch(int(st.st_mtime)).toString("MM-dd HH:mm:ss"),
            })
        self._recordings = files
        self.recordingsListChanged.emit()

    @Slot(str)
    def playRecording(self, path: str):
        self.playbackRequested.emit(path)

    @Slot()
    def resumeLive(self):
        self.livePlaybackResumed.emit()

    def setPlaybackState(self, on: bool, file: str = ""):
        changed = (self._playback_mode != on) or (self._playback_file != file)
        self._playback_mode = on
        self._playback_file = file
        if changed:
            self.playbackChanged.emit()


class InferenceWorker(QObject):
    """Runs NPU inference in a background thread; only keeps the latest frame."""
    detectionsReady = Signal(list)

    def __init__(self, detector: Detector):
        super().__init__()
        self._detector = detector
        self._latest = None
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def submit(self, arr):
        with self._cv:
            self._latest = arr  # newest overwrites — drop stale frames
            self._cv.notify()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def _loop(self):
        while True:
            with self._cv:
                while not self._stop and self._latest is None:
                    self._cv.wait()
                if self._stop:
                    return
                arr = self._latest
                self._latest = None
            try:
                dets = self._detector.infer(arr)
            except Exception as e:
                print(f"infer error: {e}", file=sys.stderr)
                continue
            self.detectionsReady.emit(dets)


PALETTE = [
    QColor("#00FF7F"), QColor("#FF6347"), QColor("#FFD700"), QColor("#1E90FF"),
    QColor("#FF69B4"), QColor("#00FFFF"), QColor("#FFA500"), QColor("#9370DB"),
    QColor("#7FFF00"), QColor("#FF4500"),
]


def _point_in_polygon(x: float, y: float, poly: list) -> bool:
    """Ray-cast point-in-polygon test. poly is list of [x,y]."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y) != (yj > y)) and \
           (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _color_for(label: str) -> QColor:
    h = 0
    for c in label:
        h = (h * 31 + ord(c)) & 0xff
    return PALETTE[h % len(PALETTE)]


class CameraManager(QObject):
    def __init__(self, video_item: VideoItem, controller: AppController,
                 detector: Detector | None, mqtt_pub: "MqttPublisher" = None, parent=None):
        super().__init__(parent)
        Gst.init(None)
        self._video_item = video_item
        self._controller = controller
        self._mqtt = mqtt_pub
        self._worker = None if detector is None else InferenceWorker(detector)
        if self._worker is not None:
            self._worker.detectionsReady.connect(self._on_detections, Qt.QueuedConnection)
        self._last_event_classes = frozenset()
        self._last_event_t = 0.0
        self._pending_dets = None
        self._current_dets = []
        self._font = QFont("sans-serif", 9)
        self._font.setBold(True)
        self._last_img = None  # latest displayed QImage for snapshot
        self._playback_runner: PlaybackRunner | None = None

        self._runners = {
            name: GstRunner(cfg["port"])
            for name, cfg in CAMERAS.items()
        }
        for r in self._runners.values():
            r.frameReady.connect(self._on_frame, Qt.QueuedConnection)
            if self._worker is not None:
                r.rawReady.connect(self._worker.submit, Qt.DirectConnection)
            r.fpsChanged.connect(controller.updateFps)
            r.bitrateChanged.connect(controller.updateBitrate)
            r.latencyChanged.connect(controller.updateLatency)
            r.linkChanged.connect(controller.updateLink)
        self._active_name = None

        # wire UI -> camera actions
        controller.snapshotRequested.connect(self._on_snapshot)
        controller.recordingRequested.connect(self._on_recording_requested)
        controller.playbackRequested.connect(self._on_playback_requested)
        controller.livePlaybackResumed.connect(self._on_live_resumed)

    def activate(self, name: str):
        if name == self._active_name:
            return
        # if recording, stop+finalize cleanly before switching cameras
        if self._controller._recording and self._active_name:
            res = self._runners[self._active_name].stop_recording()
            self._controller.setRecordingState(False)
            if res:
                threading.Thread(target=self._mux_to_mp4,
                                 args=(res[0],), daemon=True).start()
        # if playback active, stop it
        if self._playback_runner is not None:
            self._on_live_resumed()
        if self._active_name:
            self._runners[self._active_name].stop()
        self._active_name = name
        self._video_item.set_image(QImage())
        self._controller.updateDetections([])
        self._runners[name].play()

    def _on_frame(self, img: QImage):
        self._last_img = img
        # Draw detection boxes + zone polygon directly into video frame
        polygon = self._controller._zone_polygon
        zone_active = (self._controller._zone_enabled and len(polygon) >= 3)
        zone_drawing = self._controller._zone_draw_mode
        has_dets = bool(self._current_dets)
        if has_dets or polygon:
            painter = QPainter(img)
            painter.setFont(self._font)
            W, H = img.width(), img.height()

            # --- zone polygon ---
            if polygon:
                violation = self._controller._zone_violation and zone_active
                edge_col = QColor("#FF3333") if violation else (
                    QColor("#FFD700") if zone_active else QColor("#7CFCFF"))
                fill_col = QColor(edge_col)
                fill_col.setAlpha(60 if violation else 30)

                pts = [(int(p[0] * W), int(p[1] * H)) for p in polygon]
                from PySide6.QtGui import QPolygonF, QPolygon
                from PySide6.QtCore import QPoint
                qpoly = QPolygon([QPoint(x, y) for (x, y) in pts])

                pen = QPen(edge_col, 3 if violation else 2, Qt.DashLine if zone_drawing else Qt.SolidLine)
                painter.setPen(pen)
                painter.setBrush(fill_col)
                if len(pts) >= 3:
                    painter.drawPolygon(qpoly)
                else:
                    # not closed yet - just draw lines + vertices
                    for i in range(len(pts) - 1):
                        painter.drawLine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
                # vertices
                painter.setBrush(edge_col)
                for (vx, vy) in pts:
                    painter.drawEllipse(vx - 4, vy - 4, 8, 8)
                # label
                if zone_drawing:
                    painter.setPen(QColor("white"))
                    painter.drawText(10, H - 12,
                                     f"绘制中 {len(pts)}点 — 至少3点后双击/右键完成")
                elif violation:
                    painter.setPen(QColor("#FF3333"))
                    painter.drawText(10, 20, "⚠ 目标进入禁区")

            # --- detection boxes ---
            for d in self._current_dets:
                col_red = QColor("#FF3333") if d.get("in_zone") else _color_for(d["label"])
                x = int(d["x0"] * W)
                y = int(d["y0"] * H)
                w = int((d["x1"] - d["x0"]) * W)
                h = int((d["y1"] - d["y0"]) * H)
                pen = QPen(col_red, 3 if d.get("in_zone") else 2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(x, y, w, h)
                txt = f"{d['label']} {int(d['score']*100)}%"
                if d.get("in_zone"):
                    txt = "⚠ " + txt
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(txt) + 6
                th = 14
                ly = max(0, y - th)
                painter.fillRect(x, ly, tw, th, col_red)
                painter.setPen(QColor("white" if d.get("in_zone") else "black"))
                painter.drawText(x + 3, ly + th - 3, txt)
            painter.end()
        self._video_item.set_image(img)

        # Write periodic snapshot for WebUI MJPEG stream (match LCD rate, ~15fps)
        now = time.monotonic()
        if not DISABLE_SNAPSHOT_STREAM and now - getattr(self, "_snap_last_t", 0.0) > 0.06:
            self._snap_last_t = now
            try:
                img.scaled(640, 400, Qt.KeepAspectRatio).save(
                    "/tmp/skyvision-snapshot.jpg.tmp", "JPG", 65)
                os.replace("/tmp/skyvision-snapshot.jpg.tmp",
                           "/tmp/skyvision-snapshot.jpg")
            except Exception:
                pass

    def _on_detections(self, dets):
        # Boxes update every detection (drawn cheaply into video frame by QPainter).
        # Only events panel / class-change events are throttled.
        # ---- zone check (label each det with in_zone=True/False) ----
        polygon = self._controller._zone_polygon
        zone_active = self._controller._zone_enabled and len(polygon) >= 3
        any_violation = False
        for d in dets:
            cx = (d["x0"] + d["x1"]) / 2.0
            cy = (d["y0"] + d["y1"]) / 2.0
            inside = zone_active and _point_in_polygon(cx, cy, polygon)
            d["in_zone"] = inside
            if inside:
                any_violation = True

        # update controller's violation flag + fire MQTT alert on rising edge
        prev_violation = self._controller._zone_violation
        self._controller.setZoneViolation(any_violation)
        if zone_active and any_violation and not prev_violation:
            offenders = sorted({d["label"] for d in dets if d.get("in_zone")})
            self._controller.event.emit(
                "⚠ 禁区入侵: " + ", ".join(offenders), "alert")
            if self._mqtt:
                self._mqtt.publish_event(
                    "zone_violation", level="alert",
                    camera=self._active_name or "unknown",
                    labels=offenders)

        self._current_dets = dets
        self._controller.updateDetections(dets)
        if self._mqtt:
            self._mqtt.publish_detection(self._active_name or "unknown", dets)
        cur_classes = frozenset(d["label"] for d in dets)
        now = time.monotonic()
        if cur_classes != self._last_event_classes and (now - self._last_event_t) > 2.0:
            new_classes = cur_classes - self._last_event_classes
            gone_classes = self._last_event_classes - cur_classes
            if new_classes:
                self._controller.event.emit(
                    "检测到: " + ", ".join(sorted(new_classes)), "info")
                if self._mqtt:
                    self._mqtt.publish_event(
                        "object_appear", level="alert",
                        camera=self._active_name or "unknown",
                        labels=sorted(new_classes))
            if gone_classes and self._mqtt:
                self._mqtt.publish_event(
                    "object_disappear", level="info",
                    camera=self._active_name or "unknown",
                    labels=sorted(gone_classes))
            self._last_event_classes = cur_classes
            self._last_event_t = now

    # ---- snapshot ----
    def _on_snapshot(self):
        if self._last_img is None or self._last_img.isNull():
            self._controller.event.emit("无画面，截图失败", "warn")
            return
        ts = time.strftime("%Y%m%d-%H%M%S")
        out = RECORDINGS_DIR / f"snap_{self._active_name or 'cam'}_{ts}.jpg"
        # snapshot includes detection overlay since boxes painted into _last_img
        if self._last_img.save(str(out), "JPG", 90):
            self._controller.event.emit(f"截图保存: {out.name}", "info")
        else:
            self._controller.event.emit("截图保存失败", "warn")

    # ---- recording ----
    def _on_recording_requested(self, want: bool):
        if self._playback_runner is not None:
            self._controller.event.emit("回放中，无法录像", "warn")
            return
        active = self._runners.get(self._active_name)
        if active is None:
            return
        if want:
            ts = time.strftime("%Y%m%d-%H%M%S")
            h264_path = RECORDINGS_DIR / f"rec_{self._active_name}_{ts}.h264"
            if active.start_recording(h264_path):
                self._controller.setRecordingState(True)
        else:
            res = active.stop_recording()
            self._controller.setRecordingState(False)
            if res:
                h264_path, n_bytes, dur_s = res
                mb = n_bytes / 1024 / 1024
                self._controller.event.emit(
                    f"录像 {dur_s:.1f}s / {mb:.1f}MB，转码 MP4 中...", "info")
                threading.Thread(target=self._mux_to_mp4,
                                 args=(h264_path,), daemon=True).start()

    def _mux_to_mp4(self, h264_path: Path):
        mp4_path = h264_path.with_suffix(".mp4")
        cmd = (
            f'gst-launch-1.0 -q '
            f'filesrc location="{h264_path}" ! h264parse ! mp4mux ! '
            f'filesink location="{mp4_path}"'
        )
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True,
                                 timeout=300)
            ok = res.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 1024
        except Exception as e:
            print(f"mux exc: {e}", file=sys.stderr)
            ok = False
        if ok:
            try:
                h264_path.unlink()
            except Exception:
                pass
            self._controller.event.emit(f"MP4 已生成: {mp4_path.name}", "info")
        else:
            self._controller.event.emit(
                f"MP4 转码失败，保留 .h264 原始文件", "warn")

    # ---- playback ----
    def _on_playback_requested(self, path: str):
        p = Path(path)
        if not p.exists():
            self._controller.event.emit("文件不存在", "warn")
            return
        # stop live; release detection state
        if self._active_name:
            self._runners[self._active_name].stop()
        self._current_dets = []
        self._controller.updateDetections([])
        # start playback
        self._playback_runner = PlaybackRunner(p)
        self._playback_runner.frameReady.connect(
            self._on_playback_frame, Qt.QueuedConnection)
        self._playback_runner.finished.connect(
            self._on_playback_finished, Qt.QueuedConnection)
        self._playback_runner.play()
        self._controller.setPlaybackState(True, p.name)
        self._controller.event.emit(f"回放: {p.name}", "info")

    def _on_playback_frame(self, img: QImage):
        self._video_item.set_image(img)

    def _on_playback_finished(self):
        self._controller.event.emit("回放结束", "info")
        self._on_live_resumed()

    def _on_live_resumed(self):
        if self._playback_runner is not None:
            try:
                self._playback_runner.stop()
            except Exception:
                pass
            self._playback_runner = None
        self._controller.setPlaybackState(False, "")
        if self._active_name:
            self._video_item.set_image(QImage())
            self._runners[self._active_name].play()

    def stop_all(self):
        if self._playback_runner is not None:
            self._playback_runner.stop()
            self._playback_runner = None
        for r in self._runners.values():
            try:
                r.stop_recording()
            except Exception:
                pass
            r.stop()
        self._worker.stop()



sys.path.insert(0, "/root/ui-qml")
from wifi_manager import WiFiManager

def main():
    app = QGuiApplication(sys.argv)
    QQuickStyle.setStyle("Basic")

    qmlRegisterType(VideoItem, "SkyVision", 1, 0, "VideoItem")

    detector = None if DISABLE_INFERENCE else Detector()
    controller = AppController()
    mqtt_pub = MqttPublisher(MQTT_HOST, MQTT_PORT)

    # forward UI/system events to MQTT
    controller.event.connect(
        lambda msg, level: mqtt_pub.publish_event(msg, level=level))

    # Bridge link-analyzer payloads from MQTT subscriber thread to controller.
    # _link_stats_cb runs on paho-mqtt's background thread; controller property
    # updates from there are OK because we never touch QML directly — Qt's
    # property notification is fanned out by the engine on the GUI thread.
    mqtt_pub._link_stats_cb = controller.updateLinkStats
    mqtt_pub._diagnosis_cb = controller.addDiagnosisEvent

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appCtl", controller)
    wifi_mgr = WiFiManager()
    engine.rootContext().setContextProperty("wifiMgr", wifi_mgr)

    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(str(qml_path))
    if not engine.rootObjects():
        sys.exit(-1)

    root = engine.rootObjects()[0]
    video_item = root.findChild(QObject, "videoItem")
    if video_item is None:
        print("ERROR: videoItem not found in QML tree", file=sys.stderr)
        sys.exit(2)

    cam_mgr = CameraManager(video_item, controller, detector, mqtt_pub=mqtt_pub)
    controller.cameraChanged.connect(lambda: cam_mgr.activate(controller.currentCamera))
    cam_mgr.activate(controller.currentCamera)

    # periodic status heartbeat
    status_timer = QTimer()
    def _status_tick():
        mqtt_pub.publish_status(
            camera=controller.currentCamera,
            fps=round(controller._fps, 2),
            latency_ms=round(controller._latency_ms, 1),
            bitrate_mbps=round(controller._bitrate_mbps, 3),
            link=controller._link_status,
            recording=controller._recording,
        )
    status_timer.timeout.connect(_status_tick)
    status_timer.start(int(MQTT_STATUS_INTERVAL_S * 1000))

    # Signal the boot splash to stop covering /dev/fb0 after first paint.
    # 600ms delay lets QML compositor draw its first frame so the handoff is
    # seamless (otherwise user sees a flash of console/Weston background).
    def _signal_splash_done():
        try:
            open("/run/skyvision-splash-done", "w").close()
        except Exception:
            pass
    QTimer.singleShot(600, _signal_splash_done)

    rc = app.exec()
    cam_mgr.stop_all()
    mqtt_pub.stop()
    sys.exit(rc)


if __name__ == "__main__":
    main()
