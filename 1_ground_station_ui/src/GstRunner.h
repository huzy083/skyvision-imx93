#pragma once
#include <QObject>
#include <QImage>
#include <QByteArray>
#include <QTimer>
#include <QString>
#include <QMutex>
#include <atomic>
#include <cstdio>
#include <gst/gst.h>
#include <gst/app/gstappsink.h>

// One GStreamer pipeline per camera. Faithful port of Python GstRunner:
// udpsrc -> jitterbuffer -> depay -> h264parse -> tee
//   record branch (valve+appsink, raw H.264) -> writes file
//   decode branch -> avdec_h264 -> tee
//     display branch (PXP -> BGRx appsink) -> frameReady(QImage)
//     inference branch (PXP -> BGR 320x320 appsink) -> rawReady(QByteArray)
// All appsink "new-sample" callbacks run on GStreamer streaming threads; we
// emit Qt signals (queued) to marshal frames/stats onto the GUI thread, exactly
// like the Python emit-signals callbacks did.
class GstRunner : public QObject {
    Q_OBJECT
public:
    explicit GstRunner(int port, QObject *parent = nullptr);
    ~GstRunner() override;

    void play();
    void stop();

    // ---- recording (called from GUI thread) ----
    bool startRecording(const QString &path);
    // returns true and fills out params if a recording was active
    bool stopRecording(QString *path, qint64 *nBytes, double *durationS);

signals:
    void frameReady(const QImage &img);
    void rawReady(const QByteArray &bgr320);  // 320x320x3 BGR for NPU
    void fpsChanged(double fps);
    void bitrateChanged(double mbps);
    void latencyChanged(double ms);
    void linkChanged(bool linked);

private:
    static GstFlowReturn onNewSampleCb(GstAppSink *sink, gpointer user);
    static GstFlowReturn onInfSampleCb(GstAppSink *sink, gpointer user);
    static GstFlowReturn onRecSampleCb(GstAppSink *sink, gpointer user);
    GstFlowReturn onNewSample(GstAppSink *sink);
    GstFlowReturn onInfSample(GstAppSink *sink);
    GstFlowReturn onRecSample(GstAppSink *sink);

    void tick();
    static std::string makePipeline(int port);

    int m_port;
    GstElement *m_pipeline = nullptr;
    GstElement *m_recValve = nullptr;

    QTimer m_statsTimer;
    qint64 m_lastStatsT = 0;       // monotonic ns
    std::atomic<quint64> m_frameCount{0};
    std::atomic<quint64> m_byteCount{0};
    std::atomic<quint64> m_lagSumNs{0};
    std::atomic<quint64> m_lagN{0};
    bool m_linked = false;
    int m_inferSkip = 0;

    // recording state
    QMutex m_recLock;
    std::FILE *m_recFile = nullptr;
    QString m_recPath;
    qint64 m_recBytes = 0;
    qint64 m_recStartT = 0;        // monotonic ns
};
