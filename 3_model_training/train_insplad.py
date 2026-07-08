#!/usr/bin/env python3
"""YOLOv8n baseline on InsPLAD-det (18 类电力部件).

目标平台: LubanCat4 RK3588 NPU (RKNN), 机载检测。
imgsz=640: InsPLAD 为高分辨率航拍图, 部件多为小目标, 320 不够。
"""
from ultralytics import YOLO

DATA = "/home/shing/uav_ground_station/datasets/insplad/insplad_det.yaml"


def main():
    model = YOLO("yolov8n.pt")
    model.train(
        data=DATA,
        epochs=200,
        imgsz=640,
        batch=32,
        workers=8,
        device=0,
        optimizer="auto",
        amp=True,
        cache="disk",
        patience=40,
        project="/home/shing/uav_ground_station/skyvision/train/runs",
        name="yolov8n_insplad",
        exist_ok=True,
        seed=42,
    )


if __name__ == "__main__":
    main()
