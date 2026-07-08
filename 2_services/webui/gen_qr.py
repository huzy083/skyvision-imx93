#!/usr/bin/env python3
"""Single QR: WiFi connect. Captive-portal will then auto-open the WebUI."""
import qrcode
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

SSID = "SkyVision-AP"
PSK = "skyvision2026"
WIFI_PAYLOAD = f"WIFI:T:WPA;S:{SSID};P:{PSK};;"

OUT = Path("/home/shing/uav_ground_station/skyvision/ui-qml/qml/icons/webui_qr.png")

q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                  box_size=10, border=2)
q.add_data(WIFI_PAYLOAD)
q.make(fit=True)
qr_img = q.make_image(fill_color="black", back_color="white").convert("RGB")

# Compose with title + caption
pad = 30
title_h = 40
caption_h = 90
W = qr_img.width + pad * 2
H = qr_img.height + pad + title_h + caption_h
canvas = Image.new("RGB", (W, H), "white")
canvas.paste(qr_img, (pad, pad + title_h))

d = ImageDraw.Draw(canvas)
try:
    font_cn   = ImageFont.truetype(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 24)
    font_meta = ImageFont.truetype(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 16)
    font_mono = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 14)
except Exception:
    font_cn = font_meta = font_mono = ImageFont.load_default()

def centered(text, font, y, color="black"):
    bbox = d.textbbox((0, 0), text, font=font)
    d.text(((W - bbox[2]) // 2, y), text, font=font, fill=color)

centered("扫码 · 自动连 WiFi + 开页面", font_cn, pad)
cy = pad + title_h + qr_img.height + 8
centered(SSID, font_mono, cy, color="#222")
centered("连接后系统会自动弹出 WebUI", font_meta, cy + 24, color="#555")
centered("(如不弹，浏览器访问 192.168.10.1)", font_meta, cy + 48, color="#888")

OUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(OUT)
print(f"wrote {OUT}  size={canvas.size}")
