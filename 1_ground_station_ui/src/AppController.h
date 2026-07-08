#pragma once
#include "Detection.h"
#include <QObject>
#include <QTimer>
#include <QString>
#include <QVariantList>
#include <QVariantMap>
#include <QJsonObject>
#include <QVector>
#include <QPointF>

// Full C++ port of the Python AppController. Every Q_PROPERTY / Q_INVOKABLE /
// signal name is kept identical to the Python @Property/@Slot/Signal so the
// QML front-end (appCtl.*) is unchanged.
class AppController : public QObject {
    Q_OBJECT
    Q_PROPERTY(double fps READ fps NOTIFY statsChanged)
    Q_PROPERTY(double latencyMs READ latencyMs NOTIFY statsChanged)
    Q_PROPERTY(double bitrateMbps READ bitrateMbps NOTIFY statsChanged)
    Q_PROPERTY(QString linkStatus READ linkStatus NOTIFY statsChanged)
    Q_PROPERTY(QString clockText READ clockText NOTIFY clockChanged)
    Q_PROPERTY(bool recording READ recording WRITE setRecording NOTIFY recordingChanged)
    Q_PROPERTY(QString currentCamera READ currentCamera NOTIFY cameraChanged)
    Q_PROPERTY(QString cameraName READ cameraName NOTIFY cameraChanged)
    Q_PROPERTY(QVariantList detections READ detections NOTIFY detectionsChanged)
    Q_PROPERTY(int detectionCount READ detectionCount NOTIFY detectionsChanged)
    // zone alert
    Q_PROPERTY(QVariantList zonePolygon READ zonePolygon NOTIFY zoneChanged)
    Q_PROPERTY(bool zoneEnabled READ zoneEnabled NOTIFY zoneChanged)
    Q_PROPERTY(bool zoneDrawMode READ zoneDrawMode NOTIFY zoneChanged)
    Q_PROPERTY(bool zoneViolation READ zoneViolation NOTIFY zoneChanged)
    // link analyzer
    Q_PROPERTY(int linkPps READ linkPps NOTIFY linkStatsChanged)
    Q_PROPERTY(double linkKbps READ linkKbps NOTIFY linkStatsChanged)
    Q_PROPERTY(double linkRetryPct READ linkRetryPct NOTIFY linkStatsChanged)
    Q_PROPERTY(int linkRssiAvg READ linkRssiAvg NOTIFY linkStatsChanged)
    Q_PROPERTY(int linkRssiMin READ linkRssiMin NOTIFY linkStatsChanged)
    Q_PROPERTY(int linkRssiMax READ linkRssiMax NOTIFY linkStatsChanged)
    Q_PROPERTY(int linkMcsTop READ linkMcsTop NOTIFY linkStatsChanged)
    Q_PROPERTY(bool linkActive READ linkActive NOTIFY linkStatsChanged)
    // playback / recordings
    Q_PROPERTY(bool monitorMode READ monitorMode NOTIFY linkModeChanged)
    Q_PROPERTY(bool playbackMode READ playbackMode NOTIFY playbackChanged)
    Q_PROPERTY(QString playbackFile READ playbackFile NOTIFY playbackChanged)
    Q_PROPERTY(QVariantList recordings READ recordings NOTIFY recordingsListChanged)
    Q_PROPERTY(QVariantList diagLog READ diagLog NOTIFY diagLogChanged)
    Q_PROPERTY(bool screenRecording READ screenRecording NOTIFY screenRecordingChanged)
    // UAV state (FAST-LIO vs EKF2, from /tmp/skyvision-uav.json via LAN bridge)
    Q_PROPERTY(QVariantMap uavState READ uavState NOTIFY uavStateChanged)
    Q_PROPERTY(bool uavFresh READ uavFresh NOTIFY uavStateChanged)
    // 目标跟随: 0=关 1=等待点选目标 2=跟随中
    Q_PROPERTY(int followMode READ followMode NOTIFY followChanged)
    Q_PROPERTY(QString followInfo READ followInfo NOTIFY followChanged)

public:
    explicit AppController(QObject *parent = nullptr);

    // ---- property getters ----
    double fps() const { return m_fps; }
    double latencyMs() const { return m_latencyMs; }
    double bitrateMbps() const { return m_bitrateMbps; }
    QString linkStatus() const { return m_linkStatus; }
    QString clockText() const { return m_clockText; }
    bool recording() const { return m_recording; }
    void setRecording(bool v);
    QString currentCamera() const { return m_currentCamera; }
    QString cameraName() const;
    QVariantList detections() const;
    int detectionCount() const { return m_detectCount; }

    QVariantList zonePolygon() const;
    bool zoneEnabled() const { return m_zoneEnabled; }
    bool zoneDrawMode() const { return m_zoneDrawMode; }
    bool zoneViolation() const { return m_zoneViolation; }
    const QVector<QPointF> &zonePolygonPoints() const { return m_zonePolygon; }

    int linkPps() const { return m_linkPps; }
    double linkKbps() const { return m_linkKbps; }
    double linkRetryPct() const { return m_linkRetryPct; }
    int linkRssiAvg() const { return m_hasRssiAvg ? (int)m_linkRssiAvg : 0; }
    int linkRssiMin() const { return m_hasRssiMin ? m_linkRssiMin : 0; }
    int linkRssiMax() const { return m_hasRssiMax ? m_linkRssiMax : 0; }
    int linkMcsTop() const { return m_linkMcsTop; }
    bool linkActive() const;

    bool monitorMode() const { return m_monitorMode; }
    bool playbackMode() const { return m_playbackMode; }
    QString playbackFile() const { return m_playbackFile; }
    QVariantList recordings() const { return m_recordings; }
    QVariantList diagLog() const { return m_diagLog; }
    int followMode() const { return m_followMode; }
    QString followInfo() const { return m_followInfo; }
    // 供 CameraManager(跟随逻辑)回写状态/查询解锁/发自动指令
    void setFollowState(int mode, const QString &info);
    bool uavArmedNow() const {
        return m_uavFresh && m_uavState.value("armed").toBool();
    }
    void droneCommandAuto(const QString &verb) { sendDroneVerb(verb); }
    bool screenRecording() const { return m_screenRecording; }
    void setScreenRecording(bool v) {
        if (m_screenRecording == v) return;
        m_screenRecording = v;
        emit screenRecordingChanged();
    }
    QVariantMap uavState() const { return m_uavState; }
    bool uavFresh() const { return m_uavFresh; }

    // ---- called by CameraManager / bridges (not from QML) ----
    void updateDetections(const DetectionList &dets);
    const DetectionList &currentDetections() const { return m_detections; }
    void setRecordingState(bool v);
    void setZoneViolation(bool v);
    void setPlaybackState(bool on, const QString &file = "");
    void setCurrentCamera(const QString &cam);
    // Lets collaborators (CameraManager, bridges) raise the QML event feed,
    // since C++ cannot emit another object's signal directly.
    void emitEvent(const QString &text, const QString &severity) { emit event(text, severity); }

public slots:
    // stats fed from GstRunner
    void updateFps(double fps);
    void updateBitrate(double mbps);
    void updateLatency(double ms);
    void updateLink(bool linked);
    // link analyzer feed (from MQTT)
    void updateLinkStats(const QJsonObject &payload);
    void addDiagnosisEvent(const QJsonObject &payload);

    // ---- invoked from QML ----
    void snapshot();
    void toggleRecording();
    void switchCamera();
    void openZoneAlert();
    void setZoneEnabled(bool v);
    void toggleZoneDraw();
    void addZoneVertex(double nx, double ny);
    void finishZoneDraw();
    void clearZone();
    void refreshRecordings();
    void playRecording(const QString &path);
    void deleteRecording(const QString &path);
    void refreshDiagLog();
    void toggleScreenRecording() { emit screenRecordRequested(); }
    void toggleFollow();
    void videoTapped(double nx, double ny);   // 视频区点击统一入口(锁定区/跟随)
    void resumeLive();
    void toggleLinkMode();
    void shutdown();
    void droneCommand(const QString &verb);

signals:
    void statsChanged();
    void clockChanged();
    void recordingChanged();
    void cameraChanged();
    void detectionsChanged();
    void playbackChanged();
    void recordingsListChanged();
    void diagLogChanged();
    void screenRecordingChanged();
    void screenRecordRequested();
    void followChanged();
    void followSelectRequested(double nx, double ny);   // -> CameraManager命中检测
    void followCancelRequested();                       // -> CameraManager停跟随
    void zoneChanged();
    void linkStatsChanged();
    void linkModeChanged();
    void uavStateChanged();
    void event(const QString &text, const QString &severity);
    void diagnosisReceived(const QVariantMap &payload);
    // UI -> CameraManager actions
    void snapshotRequested();
    void recordingRequested(bool want);
    void playbackRequested(const QString &path);
    void livePlaybackResumed();

private slots:
    void onClockTick();

private:
    QTimer m_clockTimer;

    double m_fps = 0.0;
    double m_latencyMs = 0.0;
    double m_bitrateMbps = 0.0;
    QString m_linkStatus = QStringLiteral("等待视频");
    QString m_clockText;
    bool m_recording = false;
    QString m_currentCamera = QStringLiteral("forward");
    DetectionList m_detections;
    int m_detectCount = 0;
    bool m_monitorMode = true;
    bool m_playbackMode = false;
    QString m_playbackFile;
    QVariantList m_recordings;
    QVariantList m_diagLog;
    bool m_screenRecording = false;
    int m_followMode = 0;
    QString m_followInfo;
    void sendDroneVerb(const QString &verb);
    QVariantMap m_uavState;
    bool m_uavFresh = false;

    // zone
    QVector<QPointF> m_zonePolygon;   // normalized [0,1]
    bool m_zoneEnabled = false;
    bool m_zoneDrawMode = false;
    bool m_zoneViolation = false;

    // link analyzer
    int m_linkPps = 0;
    double m_linkKbps = 0.0;
    double m_linkRetryPct = 0.0;
    double m_linkRssiAvg = 0; bool m_hasRssiAvg = false;
    int m_linkRssiMin = 0;    bool m_hasRssiMin = false;
    int m_linkRssiMax = 0;    bool m_hasRssiMax = false;
    int m_linkMcsTop = -1;
    double m_linkLastTs = 0.0;        // epoch seconds
};
