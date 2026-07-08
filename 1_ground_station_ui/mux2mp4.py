#!/usr/bin/env python3
"""Raw H.264 elementary stream -> playable .mp4.

The C++ UI records by dumping depayloaded H.264 bytes straight to disk, so
buffers carry no PTS and a plain `h264parse ! mp4mux` bails with "Buffer has
no PTS".  This tool re-stamps timestamps: pass 1 parses the ES into access
units, pass 2 pushes them through mp4mux with PTS spread evenly across the
recording duration measured at capture time.

Usage: mux2mp4.py <in.h264> <out.mp4> [duration_s]
Exit:  0 ok, 1 gst error, 2 empty/unparseable input
"""
import sys

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst


def die(code, msg):
    print(f"mux2mp4: {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    if len(sys.argv) < 3:
        die(2, "usage: mux2mp4.py <in.h264> <out.mp4> [duration_s]")
    src, dst = sys.argv[1], sys.argv[2]
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

    Gst.init(None)

    # pass 1: parse ES into AUs (avc + codec_data caps for mp4mux)
    p1 = Gst.parse_launch(
        f'filesrc location="{src}" ! h264parse ! '
        'video/x-h264,stream-format=avc,alignment=au ! '
        'appsink name=s sync=false')
    sink = p1.get_by_name("s")
    p1.set_state(Gst.State.PLAYING)
    bufs, caps = [], None
    while True:
        sample = sink.emit("pull-sample")
        if sample is None:
            break
        if caps is None:
            caps = sample.get_caps()
        b = sample.get_buffer()
        bufs.append(b.extract_dup(0, b.get_size()))
    p1.set_state(Gst.State.NULL)

    n = len(bufs)
    if n == 0 or caps is None:
        die(2, "no access units parsed from input")
    if dur <= 0:
        dur = n / 15.0  # fallback: assume 15fps
    spf = dur / n

    # pass 2: push with synthetic PTS
    # second h264parse renegotiates cleanly (appsrc straight into mp4mux
    # fails caps negotiation) and passes our synthetic PTS through
    p2 = Gst.parse_launch(
        f'appsrc name=a format=time ! h264parse ! mp4mux ! '
        f'filesink location="{dst}"')
    asrc = p2.get_by_name("a")
    asrc.set_property("caps", caps)
    p2.set_state(Gst.State.PLAYING)
    for i, data in enumerate(bufs):
        buf = Gst.Buffer.new_wrapped(data)
        buf.pts = buf.dts = int(i * spf * Gst.SECOND)
        buf.duration = int(spf * Gst.SECOND)
        asrc.emit("push-buffer", buf)
    asrc.emit("end-of-stream")
    msg = p2.get_bus().timed_pop_filtered(
        120 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    ok = bool(msg) and msg.type == Gst.MessageType.EOS
    if not ok and msg:
        err, dbg = msg.parse_error()
        print(f"mux2mp4: gst error: {err} {dbg}", file=sys.stderr)
    p2.set_state(Gst.State.NULL)
    print(f"mux2mp4: {n} AUs, {dur:.1f}s ({n / dur:.1f}fps) -> {dst}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
