#include "AppController.h"
#include "Config.h"
#include <QDateTime>
#include <QDir>
#include <QFileInfo>
#include <QJsonValue>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QFile>
#include <QSet>
#include <QTimer>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

static double nowEpoch() { return QDateTime::currentMSecsSinceEpoch() / 1000.0; }

// /etc/skyvision-linkmode is the system's mode truth (written by switch.sh and
// the reality-follower); the UI mirrors it instead of keeping a private flip.
static bool readLinkModeFile() {
    QFile f(QStringLiteral("/etc/skyvision-linkmode"));
    if (!f.open(QIODevice::ReadOnly)) return false;
    return f.readAll().trimmed() == "mon";
}


AppController::AppController(QObject *parent) : QObject(parent) {
    m_clockTimer.setInterval(1000);
    connect(&m_clockTimer, &QTimer::timeout, this, &AppController::onClockTick);
    m_clockTimer.start();
    onClockTick();
}

QString AppController::cameraName() const {
    return cfg::cameraCfg(m_currentCamera).name;
}

QVariantList AppController::detections() const {
    QVariantList out;
    for (const auto &d : m_detections) {
        out.append(QVariantMap{
            {"x0", d.x0}, {"y0", d.y0}, {"x1", d.x1}, {"y1", d.y1},
            {"label", d.label}, {"score", d.score}, {"in_zone", d.inZone},
        });
    }
    return out;
}

QVariantList AppController::zonePolygon() const {
    QVariantList out;
    for (const QPointF &p : m_zonePolygon)
        out.append(QVariantList{p.x(), p.y()});
    return out;
}

bool AppController::linkActive() const {
    return (nowEpoch() - m_linkLastTs) < 3.0;
}

void AppController::onClockTick() {
    m_clockText = QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss");
    emit clockChanged();
    // keep the 远距/WiFi button in sync with the system mode (failover/watcher
    // can change it behind the UI's back)
    bool m = readLinkModeFile();
    if (m != m_monitorMode) {
        m_monitorMode = m;
        emit linkModeChanged();
    }
    // UAV state file, written by the uav-bridge service from the LAN broker
    QFile uf(QStringLiteral("/tmp/skyvision-uav.json"));
    bool fresh = false;
    if (uf.open(QIODevice::ReadOnly)) {
        const QJsonObject o = QJsonDocument::fromJson(uf.readAll()).object();
        if (!o.isEmpty()) {
            fresh = (QDateTime::currentMSecsSinceEpoch() / 1000.0 - o.value("ts").toDouble()) < 5.0;
            const QVariantMap map = o.toVariantMap();
            if (map != m_uavState || fresh != m_uavFresh) {
                m_uavState = map;
                m_uavFresh = fresh;
                emit uavStateChanged();
            }
        }
    }
    if (!fresh && m_uavFresh) { m_uavFresh = false; emit uavStateChanged(); }
}

// ---- recording ----
void AppController::setRecording(bool v) {
    if (m_recording == v) return;
    m_recording = v;
    emit recordingChanged();
    emit event(v ? "开始录像" : "停止录像", "info");
}

void AppController::setRecordingState(bool v) {
    if (m_recording == v) return;
    m_recording = v;
    emit recordingChanged();
    emit event(v ? "开始录像" : "停止录像", "info");
}

void AppController::toggleRecording() {
    emit recordingRequested(!m_recording);
    // state actually set by CameraManager after pipeline succeeds
}

void AppController::snapshot() {
    emit snapshotRequested();
}

// ---- camera ----
void AppController::setCurrentCamera(const QString &cam) {
    if (cam == m_currentCamera || (cam != cfg::CAM_FORWARD && cam != cfg::CAM_DOWN))
        return;
    m_currentCamera = cam;
    emit cameraChanged();
    emit event(QString("切换至 %1").arg(cfg::cameraCfg(cam).name), "info");
}

void AppController::switchCamera() {
    setCurrentCamera(m_currentCamera == cfg::CAM_FORWARD ? cfg::CAM_DOWN : cfg::CAM_FORWARD);
}

void AppController::droneCommand(const QString &verb) {
    // 手动指令入口(UI按键): 优先级高于自动跟随 —— 任何手动指令先取消跟随
    if (m_followMode != 0) {
        emit followCancelRequested();
        setFollowState(0, "");
        emit event("手动接管, 跟随已取消", "info");
    }
    sendDroneVerb(verb);
}

void AppController::sendDroneVerb(const QString &verb) {
    // "cmd <seq> <verb>" -> 127.0.0.1:5801(wfb上行入口) -> 空口 -> LubanCat执行
    // 无ACK链路: 同序号发5次(60ms间隔), 接收端按序号去重
    const QByteArray payload = QStringLiteral("cmd %1 %2")
        .arg(QDateTime::currentMSecsSinceEpoch()).arg(verb).toUtf8();
    // 按住连发的移动/偏航指令(~4Hz)不刷事件栏, 只记离散动作
    static const QSet<QString> quiet = {"fwd", "back", "left", "right",
                                        "up", "down", "yawl", "yawr"};
    if (!quiet.contains(verb))
        emit event(QStringLiteral("指令: %1").arg(verb), "warn");
    for (int i = 0; i < 5; ++i) {
        QTimer::singleShot(i * 60, this, [payload]() {
            int fd = ::socket(AF_INET, SOCK_DGRAM, 0);
            if (fd < 0) return;
            sockaddr_in a{};
            a.sin_family = AF_INET;
            a.sin_port = htons(5801);
            a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            ::sendto(fd, payload.constData(), payload.size(), 0,
                     reinterpret_cast<sockaddr *>(&a), sizeof(a));
            ::close(fd);
        });
    }
}

// ---- 目标跟随 ----
void AppController::setFollowState(int mode, const QString &info) {
    if (m_followMode == mode && m_followInfo == info) return;
    m_followMode = mode;
    m_followInfo = info;
    emit followChanged();
}

void AppController::toggleFollow() {
    if (m_followMode != 0) {
        emit followCancelRequested();
        setFollowState(0, "");
        emit event("跟随已关闭", "info");
        return;
    }
    if (!uavArmedNow()) {
        emit event("跟随: 需先起飞进入悬停", "warn");
        return;
    }
    setFollowState(1, "");
    emit event("跟随: 点击画面中的目标框选择", "info");
}

void AppController::videoTapped(double nx, double ny) {
    if (m_zoneDrawMode) {
        addZoneVertex(nx, ny);
        return;
    }
    if (m_followMode == 1)
        emit followSelectRequested(nx, ny);
}

void AppController::shutdown() {
    emit event("正在关机...", "warn");
    // detach so poweroff proceeds even as this process is torn down
    QProcess::startDetached("/bin/sh", QStringList{"-c", "sleep 1 && systemctl poweroff"});
}

// ---- stats feeds ----
void AppController::updateFps(double fps) { m_fps = fps; emit statsChanged(); }
void AppController::updateBitrate(double mbps) { m_bitrateMbps = mbps; emit statsChanged(); }
void AppController::updateLatency(double ms) { m_latencyMs = ms; emit statsChanged(); }
void AppController::updateLink(bool linked) {
    m_linkStatus = linked ? "已连接" : "等待视频";
    emit statsChanged();
}

void AppController::updateDetections(const DetectionList &dets) {
    m_detections = dets;
    m_detectCount = dets.size();
    emit detectionsChanged();
}

// ---- zone ----
void AppController::openZoneAlert() {
    emit event("打开巡检锁定区配置", "info");
}

void AppController::setZoneEnabled(bool v) {
    if (v == m_zoneEnabled) return;
    m_zoneEnabled = v;
    if (v && m_zonePolygon.size() < 3) {
        emit event("锁定区未画完整(至少3点)", "warn");
        m_zoneEnabled = false;
    } else {
        emit event(QString("锁定区 %1").arg(v ? "启用" : "关闭"), "info");
    }
    emit zoneChanged();
}

void AppController::toggleZoneDraw() {
    m_zoneDrawMode = !m_zoneDrawMode;
    if (m_zoneDrawMode) {
        m_zonePolygon.clear();
        m_zoneEnabled = false;
        emit event("锁定区绘制：在视频上依次点击 → 长按完成", "info");
    } else if (m_zonePolygon.size() >= 3) {
        emit event(QString("锁定区绘制完成(%1点)").arg(m_zonePolygon.size()), "info");
    }
    emit zoneChanged();
}

void AppController::addZoneVertex(double nx, double ny) {
    if (!m_zoneDrawMode) return;
    nx = qBound(0.0, nx, 1.0);
    ny = qBound(0.0, ny, 1.0);
    m_zonePolygon.append(QPointF(nx, ny));
    emit zoneChanged();
}

void AppController::finishZoneDraw() {
    if (m_zoneDrawMode && m_zonePolygon.size() >= 3) {
        m_zoneDrawMode = false;
        m_zoneEnabled = true;
        emit event(QString("锁定区启用(%1点)·目标进区自动诊断").arg(m_zonePolygon.size()), "info");
        emit zoneChanged();
    }
}

void AppController::clearZone() {
    m_zonePolygon.clear();
    m_zoneEnabled = false;
    m_zoneDrawMode = false;
    emit event("锁定区已清除", "info");
    emit zoneChanged();
}

void AppController::setZoneViolation(bool v) {
    if (v == m_zoneViolation) return;
    m_zoneViolation = v;
    emit zoneChanged();
}

// ---- link analyzer ----
void AppController::updateLinkStats(const QJsonObject &payload) {
    m_linkPps = payload.value("pps").toInt(0);
    m_linkKbps = payload.value("kbps").toDouble(0.0);
    m_linkRetryPct = payload.value("retry_pct").toDouble(0.0);
    if (payload.contains("rssi_avg") && !payload.value("rssi_avg").isNull()) {
        m_linkRssiAvg = payload.value("rssi_avg").toDouble();
        m_hasRssiAvg = true;
    }
    if (payload.contains("rssi_min") && !payload.value("rssi_min").isNull()) {
        m_linkRssiMin = payload.value("rssi_min").toInt();
        m_hasRssiMin = true;
    }
    if (payload.contains("rssi_max") && !payload.value("rssi_max").isNull()) {
        m_linkRssiMax = payload.value("rssi_max").toInt();
        m_hasRssiMax = true;
    }
    QJsonObject hist = payload.value("mcs_hist").toObject();
    if (!hist.isEmpty()) {
        QString topKey; double topVal = -1;
        for (auto it = hist.begin(); it != hist.end(); ++it) {
            double v = it.value().toDouble();
            if (v > topVal) { topVal = v; topKey = it.key(); }
        }
        m_linkMcsTop = topKey.toInt();
    }
    m_linkLastTs = nowEpoch();
    emit linkStatsChanged();
}

void AppController::addDiagnosisEvent(const QJsonObject &payload) {
    QString cam = payload.value("camera").toString("?");
    QString part = payload.value("part").toString("?");
    bool isDef = payload.value("is_defect").toBool(false);
    QString defect = payload.value("defect_type").toString("");
    QString reason = payload.value("reason").toString("");
    QString camCn = (cam == "forward") ? "前视" : (cam == "down") ? "下视" : cam;
    QString text, sev;
    if (isDef) {
        text = QString("[%1] %2 → 缺陷: %3 | %4").arg(camCn, part, defect, reason);
        sev = "alert";
    } else {
        text = QString("[%1] %2 正常 | %3").arg(camCn, part, reason);
        sev = "info";
    }
    emit event(text, sev);
    emit diagnosisReceived(payload.toVariantMap());
}

// ---- playback / recordings ----
void AppController::refreshRecordings() {
    QVariantList files;
    QDir dir(cfg::recordingsDir());
    // QDir::Time = 最近修改在前(按名字排会把 screen_/snap_/rec_ 混在一起难找)
    const QFileInfoList entries = dir.entryInfoList(QDir::Files, QDir::Time);
    for (const QFileInfo &fi : entries) {
        const QString suf = "." + fi.suffix();
        if (suf != ".mp4" && suf != ".h264" && suf != ".jpg" && suf != ".avi")
            continue;
        // 分类: 录屏(screen_*) / 截图(jpg: snap_*+alert_*) / 视频(相机录像)
        const QString kind = fi.fileName().startsWith("screen_") ? "screen"
                           : suf == ".jpg"                        ? "image"
                                                                  : "video";
        files.append(QVariantMap{
            {"name", fi.fileName()},
            {"path", fi.absoluteFilePath()},
            {"kind", kind},
            {"size_mb", qRound(fi.size() / 1024.0 / 1024.0 * 100) / 100.0},
            {"mtime", fi.lastModified().toString("MM-dd HH:mm:ss")},
        });
    }
    m_recordings = files;
    emit recordingsListChanged();
}

void AppController::playRecording(const QString &path) {
    emit playbackRequested(path);
}

void AppController::refreshDiagLog() {
    QVariantList out;
    QFile f(cfg::diagLogPath());
    if (f.open(QIODevice::ReadOnly | QIODevice::Text)) {
        // jsonl, one record per line; keep the newest 200, newest first
        QList<QByteArray> lines;
        while (!f.atEnd()) {
            QByteArray l = f.readLine().trimmed();
            if (!l.isEmpty()) lines.append(l);
            if (lines.size() > 200) lines.removeFirst();
        }
        for (auto it = lines.crbegin(); it != lines.crend(); ++it) {
            const QJsonObject o = QJsonDocument::fromJson(*it).object();
            if (!o.isEmpty()) out.append(o.toVariantMap());
        }
    }
    m_diagLog = out;
    emit diagLogChanged();
}

void AppController::deleteRecording(const QString &path) {
    QFileInfo fi(path);
    // refuse anything outside the recordings dir (QML hands us modelData.path)
    if (fi.absolutePath() != QDir(cfg::recordingsDir()).absolutePath())
        return;
    if (QFile::remove(fi.absoluteFilePath()))
        emit event("已删除录像: " + fi.fileName(), "info");
    else
        emit event("删除失败: " + fi.fileName(), "warn");
    refreshRecordings();
}

void AppController::resumeLive() {
    emit livePlaybackResumed();
}

void AppController::toggleLinkMode() {
    m_monitorMode = !readLinkModeFile();
    const QString mode = m_monitorMode ? "monitor" : "wifi";
    if (!QProcess::startDetached("/root/skyvision-wfb/switch.sh", {mode}))
        qWarning("[LINKMODE] failed to launch switch.sh");
    emit linkModeChanged();
}

void AppController::setPlaybackState(bool on, const QString &file) {
    bool changed = (m_playbackMode != on) || (m_playbackFile != file);
    m_playbackMode = on;
    m_playbackFile = file;
    if (changed)
        emit playbackChanged();
}
