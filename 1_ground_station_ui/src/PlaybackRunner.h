#pragma once
#include <QObject>
#include <QImage>
#include <QString>
#include <gst/gst.h>
#include <gst/app/gstappsink.h>

// Plays back a recorded .mp4/.h264 file into the same VideoItem.
// Faithful port of Python PlaybackRunner.
class PlaybackRunner : public QObject {
    Q_OBJECT
public:
    explicit PlaybackRunner(const QString &path, QObject *parent = nullptr);
    ~PlaybackRunner() override;

    void play();
    void stop();

signals:
    void frameReady(const QImage &img);
    void finished();

private:
    static GstFlowReturn onNewSampleCb(GstAppSink *sink, gpointer user);
    GstFlowReturn onNewSample(GstAppSink *sink);
    static gboolean onBusCb(GstBus *bus, GstMessage *msg, gpointer user);
    static std::string makePipeline(const QString &path);

    QString m_path;
    GstElement *m_pipeline = nullptr;
    guint m_busWatch = 0;
};
