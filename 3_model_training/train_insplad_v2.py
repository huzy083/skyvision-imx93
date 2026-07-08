"""YOLOv8n InsPLAD v2: fine-tune from v1 best.pt + 5000 COCO 负样本 + 强暗光增广.

目标：根除 closed-world false positive（无目标场景输出 sphere/glass-insulator 等）。
路径：先跑 mine_negatives_insplad.py 把 COCO 负样本下载到 train/。

数据：7935 InsPLAD 正样本 + 5000 COCO 负样本 (空 label) ≈ 1:0.63 比例
对照：PROGRESS.md P14 动物模型 5 类 + 494 COCO 负样本 mAP50 0.992→0.99
"""
from ultralytics import YOLO

DATA = "/home/shing/uav_ground_station/datasets/insplad/insplad_det.yaml"
V1_BEST = "/home/shing/uav_ground_station/skyvision/train/runs/yolov8n_insplad/weights/best.pt"


def main():
    model = YOLO(V1_BEST)
    model.train(
        data=DATA,
        epochs=30,
        imgsz=640,
        batch=32,
        workers=8,
        device=0,
        optimizer="auto",
        lr0=0.001,
        amp=True,
        cache="disk",
        patience=15,
        project="/home/shing/uav_ground_station/skyvision/train/runs",
        name="yolov8n_insplad_v2_neg",
        exist_ok=True,
        seed=42,
        # heavy augment for closed-world / dark robustness
        hsv_h=0.02,
        hsv_s=0.7,
        hsv_v=0.6,                   # default 0.4 → 0.6 更强亮度抖动
        degrees=10,
        translate=0.15,
        scale=0.6,
        fliplr=0.5,
        flipud=0.1,
        mosaic=1.0,
        mixup=0.15,                  # default 0.0 → 0.15
        copy_paste=0.1,              # default 0.0 → 0.1
        erasing=0.4,                 # default 0.4
    )


if __name__ == "__main__":
    main()
