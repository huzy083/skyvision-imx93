#!/usr/bin/env python3
"""Train YOLOv8n on SkyVision 5-class animal dataset.

Optimized for i.MX93 Ethos-U65 NPU deployment:
  - imgsz=320 (NXP recommended for Ethos-U65 throughput)
  - yolov8n.pt as backbone (smallest variant)
  - target: ~10 ms/inference on NPU after Vela compile

Run from any cwd (uses absolute paths in data.yaml).
"""
from ultralytics import YOLO


def main():
    model = YOLO("yolov8n.pt")
    results = model.train(
        data="/home/shing/uav_ground_station/skyvision/train/data.yaml",
        epochs=150,
        imgsz=320,           # NXP recommended for Ethos-U65
        batch=64,            # RTX 5070 12GB can handle this at 320x320
        workers=8,
        device=0,
        optimizer="auto",
        amp=True,
        cache="ram",
        patience=30,         # early-stop if no val improvement in 30 epochs
        project="/home/shing/uav_ground_station/skyvision/train/runs",
        name="yolov8n_skyvision_neg",
        exist_ok=True,
        seed=42,
    )
    print("training done.")
    print("best:", results.best if hasattr(results, "best") else "(see runs dir)")


if __name__ == "__main__":
    main()
