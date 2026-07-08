#pragma once
#include <QString>
#include <QByteArray>
#include <QStringList>
#include <QHash>
#include <cstdlib>

// Central place for the constants/env flags that were module-level globals in
// skyvision_ui.py. Names kept identical to ease cross-referencing.
namespace cfg {

inline bool envBool(const char *key, bool def) {
    const char *v = std::getenv(key);
    if (!v) return def;
    return QByteArray(v) == "1";
}
inline QString envStr(const char *key, const QString &def) {
    const char *v = std::getenv(key);
    return v ? QString::fromUtf8(v) : def;
}
inline int envInt(const char *key, int def) {
    const char *v = std::getenv(key);
    if (!v) return def;
    bool ok = false; int r = QByteArray(v).toInt(&ok);
    return ok ? r : def;
}
inline double envDouble(const char *key, double def) {
    const char *v = std::getenv(key);
    if (!v) return def;
    bool ok = false; double r = QByteArray(v).toDouble(&ok);
    return ok ? r : def;
}

// RTP jitterbuffer depth (ms). Dominates end-to-end latency. Env-tunable so it
// can be lowered on a clean link (was 300; 120 suits the current low-jitter WiFi).
inline int jitterBufferMs() { return envInt("SKYVISION_JITTER_MS", 120); }
constexpr int    DETECTION_INTERVAL_FRAMES   = 2;
// 0.6 太高: 飞行中有角度/距离/运动模糊, 分数在阈值线上进出 -> 框闪烁 ->
// track ID 频繁更换 -> 跟随断。0.40 配合跟踪器的 minHits=3 确认机制,
// 误检由"3帧确认"兜住而不是靠高阈值硬卡。(诊断守护另有自己的0.5过滤,
// 降这里不会增加 Qwen API 调用)
constexpr double DETECTION_SCORE_THRESHOLD   = 0.40;
constexpr double NMS_IOU_THRESHOLD           = 0.5;

inline const char *DETECTION_MODEL =
    "/usr/bin/eiq-examples-git/models/yolov8n_power_vela.tflite";
inline const char *ETHOSU_DELEGATE = "/usr/lib/libethosu_delegate.so";

inline bool disableInference()      { return envBool("SKYVISION_DISABLE_INFERENCE", false); }
inline bool disableSnapshotStream() { return envBool("SKYVISION_DISABLE_SNAPSHOT_STREAM", false); }
inline bool logFps()                { return envBool("SKYVISION_LOG_FPS", false); }

// Detection class labels — ORDER MUST MATCH the model's training data.yaml.
// Now the InsPLAD power-inspection model (yolov8n_power_merged, 16 classes;
// the 3 glass-insulator shackles are merged into one). Kept the identifier
// name for minimal churn; Detector derives class count from this list's size.
inline const QStringList ANIMAL_LABELS = {
    "yoke", "yoke suspension", "spacer", "stockbridge damper",
    "lightning rod shackle", "lightning rod suspension",
    "polymer insulator", "glass insulator", "tower id plate", "vari-grip",
    "polymer insulator lower shackle", "polymer insulator upper shackle",
    "polymer insulator tower shackle", "glass insulator shackle",
    "spiral damper", "sphere"
};

// Classes that raise a tracked "target alert" (deduped once per track id).
// Default suits the animal demo; for power inspection swap to defect classes,
// e.g. SKYVISION_ALERT_CLASSES="nest,broken_insulator,corroded_fitting".
inline QStringList alertClasses() {
    QStringList out;
    // Default empty: the 16 power classes are components, not defects, so no
    // auto-alert. Set e.g. SKYVISION_ALERT_CLASSES="bird nest" once a defect
    // model/class is added, or to flag a component of interest.
    const auto parts = envStr("SKYVISION_ALERT_CLASSES", "")
                           .split(',', Qt::SkipEmptyParts);
    for (const QString &s : parts) out << s.trimmed();
    return out;
}
inline bool isAlertClass(const QString &label) { return alertClasses().contains(label); }

// MQTT
inline QString mqttHost() { return envStr("SKYVISION_MQTT_HOST", "47.117.14.74"); }
inline int     mqttPort() { return envInt("SKYVISION_MQTT_PORT", 1883); }
inline QString mqttUser() { return envStr("SKYVISION_MQTT_USER", "skyvision"); }
inline QString mqttPass() { return envStr("SKYVISION_MQTT_PASS", ""); }
inline const char *TOPIC_DETECTION = "skyvision/detection";
inline const char *TOPIC_EVENT     = "skyvision/event";
inline const char *TOPIC_STATUS    = "skyvision/status";
inline const char *TOPIC_LINK      = "skyvision/link_stats";
inline const char *TOPIC_DIAGNOSIS = "skyvision/diagnosis";
constexpr double MQTT_DETECTION_INTERVAL_S = 0.5;
constexpr double MQTT_STATUS_INTERVAL_S    = 5.0;

inline QString recordingsDir() {
    return envStr("SKYVISION_RECORDINGS_DIR", "/opt/skyvision/recordings");
}

// Qwen-VL 诊断守护(skyvision-diag)落盘的 jsonl 记录, UI 诊断记录弹窗读取
inline QString diagLogPath() {
    return envStr("SKYVISION_DIAG_LOG", "/root/skyvision-diag/diagnosis.jsonl");
}

// ---- Battery gauge (i.MX93 ADC via resistor divider) ----
// Wiring: Vbat --[R_TOP=82k]--+(ADC in_voltageN)--[R_BOTTOM=10k]--GND
// Vadc = Vbat * R_BOTTOM/(R_TOP+R_BOTTOM); restore Vbat = Vadc * ratio.
// At 12.6V (3S full) Vadc = 1.369V, safely under the 1.8V ADC ref.
constexpr int    BAT_ADC_CHANNEL = 0;        // -> in_voltage0_raw
constexpr double BAT_R_TOP       = 82000.0;  // ohm, battery side
constexpr double BAT_R_BOTTOM    = 10000.0;  // ohm, ADC taps across this
constexpr int    BAT_CELLS       = 3;        // 3S pack (12.6V full / 9.0V empty)
constexpr int    BAT_WARN_PCT    = 20;       // low-battery warning threshold
constexpr double BAT_POLL_S      = 2.0;      // ADC sample interval
constexpr double BAT_SCALE_MV_FALLBACK = 1800.0 / 4096.0; // if in_voltage_scale unreadable

// IIO device dir (imx93-adc) and a field-calibration multiplier trimmable against
// a multimeter without recompiling (divider tolerance + ADC source-impedance sag).
inline QString batIioDir() { return envStr("SKYVISION_BAT_IIO", "/sys/bus/iio/devices/iio:device0"); }
inline double  batCal()    { return envDouble("SKYVISION_BAT_CAL", 1.0); }
inline int     batCells()  { return envInt("SKYVISION_BAT_CELLS", BAT_CELLS); }
inline bool    batEnabled(){ return !envBool("SKYVISION_BAT_DISABLE", false); }

struct CameraCfg { QString name; int port; };
// insertion order matters for switchCamera() toggle: forward <-> down
inline const QString CAM_FORWARD = "forward";
inline const QString CAM_DOWN    = "down";
inline CameraCfg cameraCfg(const QString &id) {
    if (id == CAM_DOWN) return {QStringLiteral("下视"), 5001};
    return {QStringLiteral("前视"), 5000};
}

} // namespace cfg
