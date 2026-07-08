#include "CameraManager.h"
#include "VideoItem.h"
#include "AppController.h"
#include "MqttPublisher.h"
#include "GstRunner.h"
#include "PlaybackRunner.h"
#include "Config.h"
#ifdef HAVE_TFLITE
#include "Detector.h"
#include "InferenceWorker.h"
#endif

#include <QPainter>
#include <QPen>
#include <QColor>
#include <QFile>
#include <QStringList>
#include <QFontMetrics>
#include <QPolygon>
#include <QPoint>
#include <QDir>
#include <QDateTime>
#include <QFileInfo>
#include <QJsonObject>
#include <QJsonArray>
#include <QMetaObject>
#include <cstdio>   // POSIX ::rename (atomic overwrite; QFile::rename won't overwrite)
#include <chrono>
#include <thread>
#include <cstdlib>

static double monoSec() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

static const QColor PALETTE[] = {
    QColor("#00FF7F"), QColor("#FF6347"), QColor("#FFD700"), QColor("#1E90FF"),
    QColor("#FF69B4"), QColor("#00FFFF"), QColor("#FFA500"), QColor("#9370DB"),
    QColor("#7FFF00"), QColor("#FF4500"),
};

QColor CameraManager::colorFor(const QString &label) {
    quint32 h = 0;
    for (QChar c : label)
        h = (h * 31 + c.unicode()) & 0xff;
    return PALETTE[h % (sizeof(PALETTE) / sizeof(PALETTE[0]))];
}

bool CameraManager::pointInPolygon(double x, double y, const QVector<QPointF> &poly) {
    const int n = poly.size();
    if (n < 3) return false;
    bool inside = false;
    int j = n - 1;
    for (int i = 0; i < n; ++i) {
        double xi = poly[i].x(), yi = poly[i].y();
        double xj = poly[j].x(), yj = poly[j].y();
        if (((yi > y) != (yj > y)) &&
            (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi))
            inside = !inside;
        j = i;
    }
    return inside;
}

CameraManager::CameraManager(VideoItem *videoItem, AppController *controller,
                             MqttPublisher *mqtt, QObject *parent)
    : QObject(parent), m_videoItem(videoItem), m_controller(controller), m_mqtt(mqtt) {
    m_font = QFont("sans-serif", 9);
    m_font.setBold(true);

#ifdef HAVE_TFLITE
    if (!cfg::disableInference()) {
        try {
            m_detector = new Detector();
            m_worker = new InferenceWorker(m_detector, this);
            connect(m_worker, &InferenceWorker::detectionsReady,
                    this, &CameraManager::onDetections, Qt::QueuedConnection);
        } catch (const std::exception &e) {
            qWarning("Detector init failed, inference disabled: %s", e.what());
            m_detector = nullptr;
            m_worker = nullptr;
        }
    }
#endif

    for (const QString &name : {cfg::CAM_FORWARD, cfg::CAM_DOWN}) {
        auto *r = new GstRunner(cfg::cameraCfg(name).port, this);
        m_runners.insert(name, r);
        connect(r, &GstRunner::frameReady, this, &CameraManager::onFrame, Qt::QueuedConnection);
#ifdef HAVE_TFLITE
        if (m_worker) {
            connect(r, &GstRunner::rawReady, this,
                    [this](const QByteArray &bgr) { m_worker->submit(bgr); },
                    Qt::DirectConnection);
        }
#endif
        connect(r, &GstRunner::fpsChanged, m_controller, &AppController::updateFps);
        connect(r, &GstRunner::bitrateChanged, m_controller, &AppController::updateBitrate);
        connect(r, &GstRunner::latencyChanged, m_controller, &AppController::updateLatency);
        connect(r, &GstRunner::linkChanged, m_controller, &AppController::updateLink);
    }

    // wire UI -> camera actions
    connect(m_controller, &AppController::snapshotRequested, this, &CameraManager::onSnapshot);
    connect(m_controller, &AppController::recordingRequested, this, &CameraManager::onRecordingRequested);
    connect(m_controller, &AppController::playbackRequested, this, &CameraManager::onPlaybackRequested);
    connect(m_controller, &AppController::livePlaybackResumed, this, &CameraManager::onLiveResumed);
    connect(m_controller, &AppController::followSelectRequested, this, &CameraManager::onFollowSelect);
    connect(m_controller, &AppController::followCancelRequested, this, &CameraManager::onFollowCancel);
}

CameraManager::~CameraManager() {
    stopAll();
#ifdef HAVE_TFLITE
    delete m_worker;     // joins the inference thread before the detector dies
    m_worker = nullptr;
    delete m_detector;
    m_detector = nullptr;
#endif
}

void CameraManager::activate(const QString &name) {
    if (name == m_activeName) return;
    if (m_followId >= 0) {   // 切相机 = 目标坐标系变了, 跟随必须停
        m_followId = -1;
        m_controller->setFollowState(0, "");
        m_controller->emitEvent("切换相机, 跟随已停止", "info");
    }
    // if recording, stop+finalize cleanly before switching cameras
    if (m_controller->recording() && !m_activeName.isEmpty()) {
        QString path; qint64 nb; double dur;
        bool had = m_runners[m_activeName]->stopRecording(&path, &nb, &dur);
        m_controller->setRecordingState(false);
        if (had) muxToMp4(path, dur);
    }
    if (m_playback) onLiveResumed();
    if (!m_activeName.isEmpty())
        m_runners[m_activeName]->stop();
    m_activeName = name;
    m_videoItem->setImage(QImage());
    m_controller->updateDetections({});
    m_currentDets.clear();
    m_runners[name]->play();
}

void CameraManager::onFrame(const QImage &imgIn) {
    QImage img = imgIn;          // already a detached deep copy from GstRunner
    const QVector<QPointF> &polygon = m_controller->zonePolygonPoints();
    bool zoneActive = m_controller->zoneEnabled() && polygon.size() >= 3;
    bool zoneDrawing = m_controller->zoneDrawMode();
    bool hasDets = !m_currentDets.isEmpty();

    if (hasDets || !polygon.isEmpty() || !m_tracks.isEmpty()) {
        QPainter painter(&img);
        painter.setFont(m_font);
        const int W = img.width(), H = img.height();

        // --- zone polygon ---
        if (!polygon.isEmpty()) {
            bool violation = m_controller->zoneViolation() && zoneActive;
            QColor edgeCol = violation ? QColor("#FF3333")
                            : (zoneActive ? QColor("#FFD700") : QColor("#7CFCFF"));
            QColor fillCol = edgeCol;
            fillCol.setAlpha(violation ? 60 : 30);

            QVector<QPoint> pts;
            for (const QPointF &p : polygon)
                pts.append(QPoint(int(p.x() * W), int(p.y() * H)));
            QPolygon qpoly(pts);

            QPen pen(edgeCol, violation ? 3 : 2,
                     zoneDrawing ? Qt::DashLine : Qt::SolidLine);
            painter.setPen(pen);
            painter.setBrush(fillCol);
            if (pts.size() >= 3) {
                painter.drawPolygon(qpoly);
            } else {
                for (int i = 0; i + 1 < pts.size(); ++i)
                    painter.drawLine(pts[i], pts[i + 1]);
            }
            painter.setBrush(edgeCol);
            for (const QPoint &v : pts)
                painter.drawEllipse(v.x() - 4, v.y() - 4, 8, 8);
            if (zoneDrawing) {
                painter.setPen(QColor("white"));
                painter.drawText(10, H - 12,
                    QString("绘制中 %1点 — 至少3点后双击/右键完成").arg(pts.size()));
            } else if (violation) {
                painter.setPen(QColor("#FF3333"));
                painter.drawText(10, 20, "⚠ 目标进入禁区");
            }
        }

        // --- detection boxes ---
        for (const Detection &d : m_currentDets) {
            QColor col = d.inZone ? QColor("#FF3333") : colorFor(d.label);
            int x = int(d.x0 * W), y = int(d.y0 * H);
            int w = int((d.x1 - d.x0) * W), h = int((d.y1 - d.y0) * H);
            painter.setPen(QPen(col, d.inZone ? 3 : 2));
            painter.setBrush(Qt::NoBrush);
            painter.drawRect(x, y, w, h);
            QString txt = QString("%1 %2%").arg(d.label).arg(int(d.score * 100));
            if (d.inZone) txt = "⚠ " + txt;
            QFontMetrics fm = painter.fontMetrics();
            int tw = fm.horizontalAdvance(txt) + 6;
            int th = 14;
            int ly = qMax(0, y - th);
            painter.fillRect(x, ly, tw, th, col);
            painter.setPen(QColor(d.inZone ? "white" : "black"));
            painter.drawText(x + 3, ly + th - 3, txt);
        }

        // --- tracks: trajectory trail + stable id (dedup/count visualization) ---
        for (const Track &t : m_tracks) {
            if (!t.confirmed) continue;
            const QColor tc = colorFor(t.label);
            if (t.trail.size() >= 2) {
                painter.setPen(QPen(tc, 2));
                for (int i = 1; i < t.trail.size(); ++i)
                    painter.drawLine(
                        QPointF(t.trail[i - 1].x() * W, t.trail[i - 1].y() * H),
                        QPointF(t.trail[i].x() * W,     t.trail[i].y() * H));
            }
            const QPointF c = t.center();
            painter.setPen(QColor("white"));
            painter.drawText(int(c.x() * W) + 4, int(c.y() * H) - 4,
                             QString("#%1").arg(t.id));
            if (t.id == m_followId) {   // 被跟随目标: 青色粗框+角标
                painter.setPen(QPen(QColor("#00E5FF"), 4));
                painter.drawRect(QRectF(t.x0 * W, t.y0 * H,
                                        (t.x1 - t.x0) * W, (t.y1 - t.y0) * H));
                painter.setPen(QColor("#00E5FF"));
                painter.drawText(int(t.x0 * W) + 4, int(t.y1 * H) - 6, "◎ 跟随中");
            }
        }
        painter.end();
    }
    m_lastImg = img;   // snapshot source — includes overlays painted above
    m_videoItem->setImage(img);

    // Periodic snapshot for WebUI MJPEG stream (~15fps)
    double now = monoSec();
    if (!cfg::disableSnapshotStream() && now - m_snapLastT > 0.06) {
        m_snapLastT = now;
        QImage scaled = img.scaled(640, 400, Qt::KeepAspectRatio);
        if (scaled.save("/tmp/skyvision-snapshot.jpg.tmp", "JPG", 65))
            ::rename("/tmp/skyvision-snapshot.jpg.tmp", "/tmp/skyvision-snapshot.jpg");
    }
}

void CameraManager::onDetections(const DetectionList &detsIn) {
    DetectionList dets = detsIn;
    const QVector<QPointF> &polygon = m_controller->zonePolygonPoints();
    bool zoneActive = m_controller->zoneEnabled() && polygon.size() >= 3;
    bool anyViolation = false;
    for (Detection &d : dets) {
        double cx = (d.x0 + d.x1) / 2.0;
        double cy = (d.y0 + d.y1) / 2.0;
        bool inside = zoneActive && pointInPolygon(cx, cy, polygon);
        d.inZone = inside;
        if (inside) anyViolation = true;
    }

    bool prevViolation = m_controller->zoneViolation();
    m_controller->setZoneViolation(anyViolation);
    if (zoneActive && anyViolation && !prevViolation) {
        QStringList offenders;
        for (const Detection &d : dets)
            if (d.inZone && !offenders.contains(d.label)) offenders.append(d.label);
        offenders.sort();
        m_controller->emitEvent("⚠ 锁定区: " + offenders.join(", ") + " · 已截图归档,AI诊断中", "alert");
        if (m_mqtt) {
            QJsonArray labels;
            for (const QString &l : offenders) labels.append(l);
            m_mqtt->publishEvent("zone_violation", "alert",
                QJsonObject{{"camera", m_activeName.isEmpty() ? "unknown" : m_activeName},
                            {"labels", labels}});
        }
    }

    m_currentDets = dets;
    m_controller->updateDetections(dets);
    if (m_mqtt)
        m_mqtt->publishDetection(m_activeName.isEmpty() ? "unknown" : m_activeName, dets);

    // --- cross-frame tracking: dedup/count + trajectory + per-target alert ---
    // Each physical target gets a stable id, so an alert-class target (defect,
    // dangerous animal, ...) is reported exactly once instead of every frame.
    m_tracks = m_tracker.update(dets);
    followTick();
    for (const Track &t : m_tracks) {
        if (!t.confirmed || m_alertedTrackIds.contains(t.id)) continue;
        if (!cfg::isAlertClass(t.label)) continue;
        m_alertedTrackIds.insert(t.id);
        m_controller->emitEvent(
            QString("⚠ 告警目标 #%1: %2").arg(t.id).arg(t.label), "alert");
        if (m_mqtt)
            m_mqtt->publishEvent("target_alert", "alert",
                QJsonObject{{"camera", m_activeName.isEmpty() ? "unknown" : m_activeName},
                            {"track_id", t.id}, {"label", t.label},
                            {"score", t.score}});
    }

    QSet<QString> curClasses;
    for (const Detection &d : dets) curClasses.insert(d.label);
    double now = monoSec();
    if (curClasses != m_lastEventClasses && (now - m_lastEventT) > 2.0) {
        QSet<QString> newClasses = curClasses - m_lastEventClasses;
        QSet<QString> goneClasses = m_lastEventClasses - curClasses;
        if (!newClasses.isEmpty()) {
            QStringList nc(newClasses.begin(), newClasses.end());
            nc.sort();
            m_controller->emitEvent("检测到: " + nc.join(", "), "info");
            if (m_mqtt) {
                QJsonArray labels;
                for (const QString &l : nc) labels.append(l);
                m_mqtt->publishEvent("object_appear", "alert",
                    QJsonObject{{"camera", m_activeName.isEmpty() ? "unknown" : m_activeName},
                                {"labels", labels}});
            }
        }
        if (!goneClasses.isEmpty() && m_mqtt) {
            QStringList gc(goneClasses.begin(), goneClasses.end());
            gc.sort();
            QJsonArray labels;
            for (const QString &l : gc) labels.append(l);
            m_mqtt->publishEvent("object_disappear", "info",
                QJsonObject{{"camera", m_activeName.isEmpty() ? "unknown" : m_activeName},
                            {"labels", labels}});
        }
        m_lastEventClasses = curClasses;
        m_lastEventT = now;
    }
}

// ---- snapshot ----
void CameraManager::onSnapshot() {
    if (m_lastImg.isNull()) {
        m_controller->emitEvent("无画面，截图失败", "warn");
        return;
    }
    QString ts = QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss");
    QString cam = m_activeName.isEmpty() ? "cam" : m_activeName;
    QString out = QDir(cfg::recordingsDir()).filePath(QString("snap_%1_%2.jpg").arg(cam, ts));
    if (m_lastImg.save(out, "JPG", 90))
        m_controller->emitEvent("截图保存: " + QFileInfo(out).fileName(), "info");
    else
        m_controller->emitEvent("截图保存失败", "warn");
}

// ---- recording ----
void CameraManager::onRecordingRequested(bool want) {
    if (m_playback) {
        m_controller->emitEvent("回放中，无法录像", "warn");
        return;
    }
    GstRunner *active = m_runners.value(m_activeName, nullptr);
    if (!active) return;
    if (want) {
        QString ts = QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss");
        QString h264 = QDir(cfg::recordingsDir())
                           .filePath(QString("rec_%1_%2.h264").arg(m_activeName, ts));
        if (active->startRecording(h264))
            m_controller->setRecordingState(true);
    } else {
        QString path; qint64 nb; double dur;
        bool had = active->stopRecording(&path, &nb, &dur);
        m_controller->setRecordingState(false);
        if (had) {
            double mb = nb / 1024.0 / 1024.0;
            m_controller->emitEvent(
                QString("录像 %1s / %2MB，转码 MP4 中...")
                    .arg(dur, 0, 'f', 1).arg(mb, 0, 'f', 1), "info");
            muxToMp4(path, dur);
        }
    }
}

void CameraManager::muxToMp4(const QString &h264Path, double durationS) {
    AppController *ctl = m_controller;
    std::thread([h264Path, durationS, ctl]() {
        QString mp4 = h264Path;
        mp4.chop(QStringLiteral(".h264").size());
        mp4 += ".mp4";
        // the raw ES we record carries no PTS, so plain h264parse!mp4mux dies
        // with "Buffer has no PTS" — the helper re-stamps timestamps spread
        // over the measured recording duration, then muxes
        QString cmd = QString("python3 /opt/skyvision/mux2mp4.py \"%1\" \"%2\" %3")
                          .arg(h264Path, mp4,
                               QString::number(durationS, 'f', 1));
        int rc = std::system(cmd.toLocal8Bit().constData());
        QFileInfo fi(mp4);
        bool ok = (rc == 0) && fi.exists() && fi.size() > 1024;
        if (ok) QFile::remove(h264Path);
        QString msg = ok ? ("MP4 已生成: " + fi.fileName())
                         : "MP4 转码失败，保留 .h264 原始文件";
        QString sev = ok ? "info" : "warn";
        QMetaObject::invokeMethod(ctl, [ctl, msg, sev] { ctl->emitEvent(msg, sev); },
                                  Qt::QueuedConnection);
    }).detach();
}

// ---- 目标跟随 ----
// 点选: 命中包含点击点的最小 track 框(多目标重叠时选最具体的那个)
void CameraManager::onFollowSelect(double nx, double ny) {
    if (m_activeName != cfg::CAM_FORWARD) {
        m_controller->emitEvent("跟随仅支持前视相机", "warn");
        m_controller->setFollowState(0, "");
        return;
    }
    const Track *best = nullptr;
    float bestArea = 1e9f;
    for (const Track &t : m_tracks) {
        if (!t.confirmed) continue;
        if (nx < t.x0 || nx > t.x1 || ny < t.y0 || ny > t.y1) continue;
        float area = (t.x1 - t.x0) * (t.y1 - t.y0);
        if (area < bestArea) { bestArea = area; best = &t; }
    }
    if (!best) {
        m_controller->emitEvent("该位置没有目标框, 再点一次", "warn");
        return;   // 停留在点选模式
    }
    m_followId = best->id;
    m_followLabel = best->label;
    m_followEma = best->center();
    m_followLostT = 0.0;
    m_followLastCmd = 0.0;
    m_controller->setFollowState(2, QString("#%1 %2").arg(best->id).arg(best->label));
    m_controller->emitEvent(
        QString("开始跟随 #%1 %2 (按任意方向键接管)").arg(best->id).arg(best->label), "info");
}

void CameraManager::onFollowCancel() {
    m_followId = -1;
    m_followLabel.clear();
    m_followEma = QPointF();
    m_followLostT = 0.0;
}

// 每个推理周期调一次: 把目标框中心往画面中心压(偏航+升降小步修正)。
// 修正指令复用手动按键的 verb 通道 -> 机上限幅/悬停逻辑全部继承, 无跑飞路径。
void CameraManager::followTick() {
    if (m_followId < 0) return;
    // 落地/失联即停
    if (!m_controller->uavArmedNow()) {
        m_followId = -1;
        m_controller->setFollowState(0, "");
        m_controller->emitEvent("跟随停止(已上锁/无人机数据丢失)", "warn");
        return;
    }
    const Track *ft = nullptr;
    for (const Track &t : m_tracks)
        if (t.id == m_followId) { ft = &t; break; }
    double now = monoSec();
    if (!ft) {
        // ID没了(检测闪烁会让tracker换ID): 4s内按"同类别+近位置"重新锁定
        if (m_followLostT <= 0.0) m_followLostT = now;
        const Track *cand = nullptr;
        float bestD2 = 0.30f * 0.30f;   // 归一化距离上限
        for (const Track &t : m_tracks) {
            if (!t.confirmed || t.label != m_followLabel) continue;
            const QPointF d = t.center() - m_followEma;
            const float d2 = float(d.x() * d.x() + d.y() * d.y());
            if (d2 < bestD2) { bestD2 = d2; cand = &t; }
        }
        if (cand) {
            m_followId = cand->id;
            m_followLostT = 0.0;
            m_controller->setFollowState(2, QString("#%1 %2").arg(cand->id).arg(cand->label));
            m_controller->emitEvent(QString("重新锁定 #%1 %2").arg(cand->id).arg(cand->label), "info");
            ft = cand;
        } else if (now - m_followLostT > 4.0) {
            m_followId = -1;
            m_controller->setFollowState(0, "");
            m_controller->emitEvent("跟随目标丢失, 已停止(悬停保持)", "warn");
            return;
        } else {
            return;   // 等目标重现, 期间不动
        }
    }
    m_followLostT = 0.0;
    // 中心做EMA平滑, 抗单帧框抖动
    const QPointF c = ft->center();
    m_followEma = m_followEma.isNull() ? c
                : QPointF(m_followEma.x() * 0.6 + c.x() * 0.4,
                          m_followEma.y() * 0.6 + c.y() * 0.4);
    if (now - m_followLastCmd < 0.5)   // 2Hz限频: 闭环经空口往返, 增益必须温和
        return;
    const double dx = m_followEma.x() - 0.5;   // >0 目标在画面右侧
    const double dy = m_followEma.y() - 0.5;   // >0 目标在画面下方
    bool sent = false;
    if (dx > 0.06)       { m_controller->droneCommandAuto("yawr"); sent = true; }
    else if (dx < -0.06) { m_controller->droneCommandAuto("yawl"); sent = true; }
    if (dy > 0.08)       { m_controller->droneCommandAuto("down"); sent = true; }
    else if (dy < -0.08) { m_controller->droneCommandAuto("up");   sent = true; }
    if (sent) m_followLastCmd = now;
}

// ---- playback ----
void CameraManager::onPlaybackRequested(const QString &path) {
    QFileInfo fi(path);
    if (!fi.exists()) {
        m_controller->emitEvent("文件不存在", "warn");
        return;
    }
    if (!m_activeName.isEmpty())
        m_runners[m_activeName]->stop();
    m_currentDets.clear();
    m_controller->updateDetections({});
    m_playback = new PlaybackRunner(path, this);
    connect(m_playback, &PlaybackRunner::frameReady, this,
            &CameraManager::onPlaybackFrame, Qt::QueuedConnection);
    connect(m_playback, &PlaybackRunner::finished, this,
            &CameraManager::onPlaybackFinished, Qt::QueuedConnection);
    m_playback->play();
    m_controller->setPlaybackState(true, fi.fileName());
    m_controller->emitEvent("回放: " + fi.fileName(), "info");
}

void CameraManager::onPlaybackFrame(const QImage &img) {
    m_videoItem->setImage(img);
}

void CameraManager::onPlaybackFinished() {
    m_controller->emitEvent("回放结束", "info");
    onLiveResumed();
}

void CameraManager::onLiveResumed() {
    if (m_playback) {
        m_playback->stop();
        m_playback->deleteLater();
        m_playback = nullptr;
    }
    m_controller->setPlaybackState(false, "");
    if (!m_activeName.isEmpty()) {
        m_videoItem->setImage(QImage());
        m_runners[m_activeName]->play();
    }
}

void CameraManager::stopAll() {
    if (m_playback) {
        m_playback->stop();
        m_playback->deleteLater();
        m_playback = nullptr;
    }
    for (GstRunner *r : m_runners) {
        QString p; qint64 nb; double dur;
        r->stopRecording(&p, &nb, &dur);
        r->stop();
    }
#ifdef HAVE_TFLITE
    if (m_worker) m_worker->stop();
#endif
}
