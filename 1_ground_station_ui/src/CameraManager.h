#pragma once
#include "Detection.h"
#include "Tracker.h"
#include <QObject>
#include <QHash>
#include <QImage>
#include <QFont>
#include <QString>
#include <QSet>
#include <QPointF>
#include <QVector>

class VideoItem;
class AppController;
class MqttPublisher;
class GstRunner;
class PlaybackRunner;
#ifdef HAVE_TFLITE
class Detector;
class InferenceWorker;
#endif

// Orchestrates the per-camera GstRunners, paints detection/zone overlays into
// each frame, and handles recording/playback/snapshot. Faithful port of the
// Python CameraManager.
class CameraManager : public QObject {
    Q_OBJECT
public:
    CameraManager(VideoItem *videoItem, AppController *controller,
                  MqttPublisher *mqtt, QObject *parent = nullptr);
    ~CameraManager() override;

    void activate(const QString &name);
    void stopAll();

private slots:
    void onFrame(const QImage &img);
    void onDetections(const DetectionList &dets);
    void onFollowSelect(double nx, double ny);
    void onFollowCancel();
    void onSnapshot();
    void onRecordingRequested(bool want);
    void onPlaybackRequested(const QString &path);
    void onPlaybackFrame(const QImage &img);
    void onPlaybackFinished();
    void onLiveResumed();

private:
    void muxToMp4(const QString &h264Path, double durationS = 0.0);
    void followTick();
    static QColor colorFor(const QString &label);
    static bool pointInPolygon(double x, double y, const QVector<QPointF> &poly);

    VideoItem *m_videoItem;
    AppController *m_controller;
    MqttPublisher *m_mqtt;

    QHash<QString, GstRunner *> m_runners;
    QString m_activeName;
    PlaybackRunner *m_playback = nullptr;

#ifdef HAVE_TFLITE
    Detector *m_detector = nullptr;
    InferenceWorker *m_worker = nullptr;
#endif

    QFont m_font;
    QImage m_lastImg;
    DetectionList m_currentDets;
    Tracker m_tracker;             // cross-frame IOU tracker (dedup/count/trajectory)
    QVector<Track> m_tracks;       // live tracks from the last detection cycle
    QSet<int> m_alertedTrackIds;   // track ids already alerted on (report-once dedup)
    QSet<QString> m_lastEventClasses;
    double m_lastEventT = 0.0;     // monotonic seconds
    double m_snapLastT = 0.0;
    int m_followId = -1;           // 跟随中的 track id, -1=未跟随
    double m_followLastCmd = 0.0;  // 上次发跟随修正指令的时刻(限频)
    QString m_followLabel;         // 被跟目标类别(ID丢失后按类别+近位置重锁)
    QPointF m_followEma;           // 平滑后的目标中心(抗检测框抖动)
    double m_followLostT = 0.0;    // 目标丢失起始时刻, 0=在跟
};
