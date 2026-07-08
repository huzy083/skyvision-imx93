# SkyVision——基于 FRDM-i.MX93 边缘 NPU 的无人机电力巡检智能地面终端

全国大学生嵌入式芯片与系统设计竞赛'2026（芯片应用赛道·恩智浦半导体赛题）参赛作品软件代码包（地面智能终端侧）。

地面终端以 NXP FRDM-i.MX93 为核心：接收无人机经 wfb-ng（远距广播）/ WiFi AP（近距）
双模无线链路回传的视频，在本地完成 H.264 解码、Ethos-U65 NPU 实时检测（18 类电力
部件）、跨帧跟踪、巡检锁定区告警与截图归档，并按需调用云端多模态大模型进行缺陷复核；
同时经无线控制通道下发一键起飞、航点巡检、目标跟随与智能返航指令，Cortex-M33 实时核
承担电池电量采样。系统架构见 `4_docs/figs/skyvision_sysarch.png`。

## 目录结构

```
1_ground_station_ui/     地面站主程序（C++/Qt-QML，运行于 i.MX93 Cortex-A55）
├── src/                 C++ 源码：视频管线/NPU 推理/IoU 跟踪器/锁定区/目标跟随/
│                        飞控指令链/录像录屏回放/电量监测 等
├── qml/                 界面（QML，运行时从磁盘加载，改界面无需重编译）
├── CMakeLists.txt       构建配置（-DWITH_TFLITE=ON -DWITH_MOSQUITTO=ON）
├── cross-build.sh       交叉编译脚本（开发机 x86 → aarch64，含 sysroot 制作）
├── aarch64-board.cmake  交叉工具链定义
├── skyvision_ui.py      Python 原型（自研，验证方案后由 C++ 重写，保留作对照）
└── mux2mp4.py           录像封装工具（为无时间戳裸 H.264 流补 PTS 后封装 MP4）

2_services/              地面终端伴随服务（均为 systemd 自启，Python）
├── webui/               手机 WebUI（标准库 HTTP/SSE + MJPEG 快照流，端口 8080，
│                        含 captive-portal 重定向，扫码即用）
├── diagnosis/           Qwen-VL 缺陷诊断守护（锁定区触发加急、按目标节流、
│                        结论回显与 jsonl 留痕归档）
└── link-analyzer/       wfb 链路质量分析（RSSI/丢包统计 → MQTT → 界面）

3_model_training/        检测模型训练与数据准备脚本
├── coco2yolo_insplad.py   InsPLAD 数据集格式转换
├── train_insplad*.py      YOLOv8n 训练
├── mine_negatives*.py     负样本挖掘（降低误检）
└── board_infer.py         Vela(Ethos-U) 模型板上推理验证（与 C++ 后处理逐位对齐）

4_docs/figs/             系统整体框图 / 锁定区诊断流程图 / 自制电量采样电路图
```

## 构建与部署（地面站主程序）

板上仅有 Qt6 运行库（无 moc/编译工具），需在开发机交叉编译：

```bash
cd 1_ground_station_ui
./cross-build.sh          # 制作 sysroot（从板上拉取）+ host moc + 配置 + 编译
scp build/skyvision_ui root@<板子IP>:/root/ui-qml/skyvision_ui_cpp
scp -r qml root@<板子IP>:/root/ui-qml/
```

模型：YOLOv8n 经 INT8 量化后按 NXP eIQ 官方流程（AN14357）用 Vela 编译，
运行时经 ethosu delegate 调度至 Ethos-U65 NPU。

## 配置

服务的 MQTT 地址/账号通过环境变量注入（代码内不含密钥）：

```
SKYVISION_MQTT_HOST / SKYVISION_MQTT_PORT / SKYVISION_MQTT_USER / SKYVISION_MQTT_PASS
DASHSCOPE_API_KEY        # 大模型诊断（可选增强，无网时检测与告警不受影响）
```

## 主要第三方依赖

Qt6 / GStreamer / TensorFlow Lite (+ethos-u delegate) / libmosquitto /
wfb-ng / Ultralytics YOLOv8 / paho-mqtt。
以上均为开源组件，本包内代码为参赛队自研；机载端（飞控与定位）基于
PX4 / MAVROS / FAST-LIO2 开源生态搭建，不在本包范围内。
