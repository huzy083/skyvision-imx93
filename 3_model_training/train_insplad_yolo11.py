#!/usr/bin/env python3
"""YOLO11n on InsPLAD-det — 专做论文对比表(vs yolov8n)。

与 train_insplad.py 同超参,只换 backbone,保证对比公平。
"""
from ultralytics import YOLO

DATA = "/home/shing/uav_ground_station/datasets/insplad/insplad_det.yaml"


def main():
    model = YOLO("yolo11n.pt")
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
        name="yolo11n_insplad",
        exist_ok=True,
        seed=42,
    )


if __name__ == "__main__":
    main()
