#!/usr/bin/env python3
"""SkyVision link analyzer — IW612 monitor mode link health metrics.

Captures 802.11 frames on mon0 (with radiotap header), filters by SkyVision-AP
BSSID + station MAC, computes per-second:
  - PPS (frames/s involving our link)
  - kbps (raw 802.11 throughput including retransmits)
  - retry_pct (802.11 MAC-layer retry rate, invisible at IP layer)
  - rssi_avg / min / max (per-packet over-the-air signal)
  - mcs distribution (rate adaptation behavior)

Publishes JSON to MQTT topic `skyvision/link_stats` every 1s.

This is "Tier 1" of the IW612 monitor mode story: even without LubanCat-side
injection (no monitor-capable WiFi card), we still demonstrate IW612 monitor
mode as a fine-grained PHY-layer diagnostics channel — something standard
`iw station dump` cannot provide.
"""
import json
import os
import socket
import struct
import sys
import threading
import time

import paho.mqtt.client as mqtt

# ---- config ----
MON_IFACE = os.environ.get("SKYVISION_MON_IFACE", "mon0")

# Frames we care about: anything where addr1, addr2, or addr3 is one of these.
# - uap0 BSSID (SkyVision-AP)
# - currently-known station MACs (auto-learned at runtime as well)
OUR_MACS = {
    bytes.fromhex("02005e534b59"),     # uap0 BSSID
}

MQTT_HOST = os.environ.get("SKYVISION_MQTT_HOST", "47.117.14.74")
MQTT_PORT = int(os.environ.get("SKYVISION_MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("SKYVISION_MQTT_USER", "skyvision")
MQTT_PASS = os.environ.get("SKYVISION_MQTT_PASS", "")

# ---- radiotap parsing ----
# Per https://www.radiotap.org/ — only the fields we need
RT_PRESENT_TSFT     = 1 << 0
RT_PRESENT_FLAGS    = 1 << 1
RT_PRESENT_RATE     = 1 << 2
RT_PRESENT_CHANNEL  = 1 << 3
RT_PRESENT_FHSS     = 1 << 4
RT_PRESENT_ANTSIG   = 1 << 5
RT_PRESENT_ANTNOISE = 1 << 6
RT_PRESENT_LOCK     = 1 << 7
RT_PRESENT_TXATT    = 1 << 8
RT_PRESENT_DBTXATT  = 1 << 9
RT_PRESENT_DBMTXPWR = 1 << 10
RT_PRESENT_ANTENNA  = 1 << 11
RT_PRESENT_DBANTSIG = 1 << 12
RT_PRESENT_DBANTNOISE = 1 << 13
RT_PRESENT_RX_FLAGS = 1 << 14
RT_PRESENT_MCS      = 1 << 19
RT_PRESENT_EXT      = 1 << 31


def _align(off, a):
    return (off + a - 1) & ~(a - 1)


def parse_radiotap(pkt):
    """Returns (rt_len, rssi_dbm, mcs_index) — rssi_dbm/mcs may be None."""
    if len(pkt) < 8:
        return None
    rt_len = struct.unpack_from("<H", pkt, 2)[0]
    if rt_len < 8 or rt_len > len(pkt):
        return None
    present0 = struct.unpack_from("<I", pkt, 4)[0]

    # Skip extension present words
    off = 8
    p = present0
    while p & RT_PRESENT_EXT:
        if off + 4 > rt_len:
            return rt_len, None, None
        p = struct.unpack_from("<I", pkt, off)[0]
        off += 4

    rssi = None
    mcs = None

    # Walk fields in defined order (only present ones consume bytes)
    if present0 & RT_PRESENT_TSFT:
        off = _align(off, 8) + 8
    if present0 & RT_PRESENT_FLAGS:
        off += 1
    if present0 & RT_PRESENT_RATE:
        off += 1
    if present0 & RT_PRESENT_CHANNEL:
        off = _align(off, 2) + 4
    if present0 & RT_PRESENT_FHSS:
        off += 2
    if present0 & RT_PRESENT_ANTSIG:
        if off < rt_len:
            rssi = struct.unpack_from("b", pkt, off)[0]
        off += 1
    if present0 & RT_PRESENT_ANTNOISE:
        off += 1
    if present0 & RT_PRESENT_LOCK:
        off = _align(off, 2) + 2
    if present0 & RT_PRESENT_TXATT:
        off = _align(off, 2) + 2
    if present0 & RT_PRESENT_DBTXATT:
        off = _align(off, 2) + 2
    if present0 & RT_PRESENT_DBMTXPWR:
        off += 1
    if present0 & RT_PRESENT_ANTENNA:
        off += 1
    if present0 & RT_PRESENT_DBANTSIG:
        off += 1
    if present0 & RT_PRESENT_DBANTNOISE:
        off += 1
    if present0 & RT_PRESENT_RX_FLAGS:
        off = _align(off, 2) + 2
    if present0 & RT_PRESENT_MCS:
        if off + 3 <= rt_len:
            mcs_known = pkt[off]
            mcs_flags = pkt[off + 1]
            mcs_index = pkt[off + 2]
            if mcs_known & 0x02:  # MCS index known
                mcs = mcs_index
        off += 3

    return rt_len, rssi, mcs


# ---- shared metrics state ----
class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.frames = 0
        self.bytes = 0
        self.retries = 0
        self.rssi_sum = 0
        self.rssi_count = 0
        self.rssi_min = None
        self.rssi_max = None
        self.mcs_hist = {}

    def add(self, length, rssi, retry, mcs):
        self.frames += 1
        self.bytes += length
        if retry:
            self.retries += 1
        if rssi is not None:
            self.rssi_sum += rssi
            self.rssi_count += 1
            self.rssi_min = rssi if self.rssi_min is None else min(self.rssi_min, rssi)
            self.rssi_max = rssi if self.rssi_max is None else max(self.rssi_max, rssi)
        if mcs is not None:
            self.mcs_hist[mcs] = self.mcs_hist.get(mcs, 0) + 1


STATS = Stats()


def reader_loop():
    ETH_P_ALL = 0x0003
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    s.bind((MON_IFACE, 0))
    s.settimeout(1.0)
    print(f"[reader] bound to {MON_IFACE}", file=sys.stderr, flush=True)

    while True:
        try:
            pkt = s.recv(2300)
        except socket.timeout:
            continue
        except OSError as e:
            print(f"[reader] recv error: {e}", file=sys.stderr, flush=True)
            time.sleep(0.5)
            continue

        rt = parse_radiotap(pkt)
        if rt is None:
            continue
        rt_len, rssi, mcs = rt
        if rt_len + 24 > len(pkt):
            continue

        d11 = pkt[rt_len:]
        # 802.11 frame control: 2 bytes
        fc0 = d11[0]
        fc1 = d11[1]
        ftype = (fc0 >> 2) & 0x3
        # Control frames (type=1) have shorter headers; addr1 is still at offset 4
        if ftype == 1 and len(d11) >= 10:
            addr1 = d11[4:10]
            if addr1 not in OUR_MACS:
                continue
            STATS.add(len(pkt), rssi, retry=bool(fc1 & 0x08), mcs=mcs)
            continue
        # Mgmt (0) and Data (2) frames have addr1, addr2, addr3
        if len(d11) < 24:
            continue
        addr1 = d11[4:10]
        addr2 = d11[10:16]
        addr3 = d11[16:22]
        if not (addr1 in OUR_MACS or addr2 in OUR_MACS or addr3 in OUR_MACS):
            continue
        retry = bool(fc1 & 0x08)  # 802.11 FC retry bit
        STATS.add(len(pkt), rssi, retry=retry, mcs=mcs)


def reporter_loop(mqtt_client):
    while True:
        time.sleep(1.0)
        with STATS.lock:
            frames = STATS.frames
            bytes_ct = STATS.bytes
            retries = STATS.retries
            rssi_avg = (STATS.rssi_sum / STATS.rssi_count) if STATS.rssi_count else None
            rssi_min = STATS.rssi_min
            rssi_max = STATS.rssi_max
            mcs_hist = dict(STATS.mcs_hist)
            STATS.reset()

        payload = {
            "ts": time.time(),
            "pps": frames,
            "kbps": round(bytes_ct * 8 / 1024, 1),
            "retry_pct": round(retries / frames * 100, 1) if frames > 0 else 0,
            "rssi_avg": round(rssi_avg, 1) if rssi_avg is not None else None,
            "rssi_min": rssi_min,
            "rssi_max": rssi_max,
            "mcs_hist": mcs_hist,
        }
        try:
            mqtt_client.publish("skyvision/link_stats", json.dumps(payload), qos=0)
        except Exception as e:
            print(f"[reporter] publish error: {e}", file=sys.stderr, flush=True)


def main():
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=f"link-analyzer-{os.getpid()}")
    except AttributeError:
        client = mqtt.Client(client_id=f"link-analyzer-{os.getpid()}")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS or None)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    try:
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        client.loop_start()
        print(f"[mqtt] connecting {MQTT_HOST}:{MQTT_PORT}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[mqtt] init fail: {e}", file=sys.stderr, flush=True)

    threading.Thread(target=reporter_loop, args=(client,), daemon=True).start()
    reader_loop()


if __name__ == "__main__":
    main()
