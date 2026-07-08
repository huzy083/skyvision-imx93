#include "GstRunner.h"
#include "Config.h"
#include <gst/gstclock.h>
#include <string>

static qint64 monoUs() { return g_get_monotonic_time(); }  // microseconds

std::string GstRunner::makePipeline(int port) {
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%d", port);
    const std::string p(buf);
    std::snprintf(buf, sizeof(buf), "%d", cfg::jitterBufferMs());
    const std::string jb(buf);

    std::string pipeline =
        "udpsrc port=" + p + " buffer-size=32768 "
        "caps=\"application/x-rtp,media=video,clock-rate=90000,encoding-name=H264,payload=96\" ! "
        "rtpjitterbuffer name=jb latency=" + jb + " do-lost=false drop-on-latency=false ! "
        "rtph264depay ! h264parse config-interval=-1 ! "
        "tee name=raw_t "
        // record branch: gated by valve; appsink hands raw H.264 NALs out
        "raw_t. ! queue max-size-buffers=400 max-size-time=4000000000 max-size-bytes=0 leaky=no ! "
        "valve name=rec_valve drop=true ! "
        "video/x-h264,stream-format=byte-stream,alignment=au ! "
        "appsink name=recsink emit-signals=true max-buffers=10 drop=true sync=false async=false "
        // decode branch: feeds the display+inference tee
        "raw_t. ! queue max-size-buffers=1 leaky=downstream ! "
        "avdec_h264 max-threads=2 thread-type=2 output-corrupt=false ! "
        "tee name=t "
        // display branch
        "t. ! queue max-size-buffers=1 leaky=downstream ! "
        "imxvideoconvert_pxp ! "
        "video/x-raw,format=BGRx ! "
        "appsink name=sink emit-signals=true max-buffers=1 drop=true sync=false ";
    if (!cfg::disableInference()) {
        pipeline +=
            "t. ! queue max-size-buffers=1 leaky=downstream ! "
            "imxvideoconvert_pxp ! "
            "video/x-raw,format=BGR,width=320,height=320 ! "
            "appsink name=infsink emit-signals=true max-buffers=1 drop=true sync=false";
    }
    return pipeline;
}

GstRunner::GstRunner(int port, QObject *parent)
    : QObject(parent), m_port(port) {
    GError *err = nullptr;
    const std::string desc = makePipeline(port);
    m_pipeline = gst_parse_launch(desc.c_str(), &err);
    if (!m_pipeline) {
        qWarning("GstRunner: parse_launch failed: %s", err ? err->message : "(null)");
        if (err) g_error_free(err);
        return;
    }

    GstElement *sink = gst_bin_get_by_name(GST_BIN(m_pipeline), "sink");
    if (sink) {
        GstAppSinkCallbacks cb{};
        cb.new_sample = &GstRunner::onNewSampleCb;
        gst_app_sink_set_callbacks(GST_APP_SINK(sink), &cb, this, nullptr);
        gst_object_unref(sink);
    }
    GstElement *infsink = gst_bin_get_by_name(GST_BIN(m_pipeline), "infsink");
    if (infsink) {
        GstAppSinkCallbacks cb{};
        cb.new_sample = &GstRunner::onInfSampleCb;
        gst_app_sink_set_callbacks(GST_APP_SINK(infsink), &cb, this, nullptr);
        gst_object_unref(infsink);
    }
    m_recValve = gst_bin_get_by_name(GST_BIN(m_pipeline), "rec_valve");  // kept ref
    GstElement *recsink = gst_bin_get_by_name(GST_BIN(m_pipeline), "recsink");
    if (recsink) {
        GstAppSinkCallbacks cb{};
        cb.new_sample = &GstRunner::onRecSampleCb;
        gst_app_sink_set_callbacks(GST_APP_SINK(recsink), &cb, this, nullptr);
        gst_object_unref(recsink);
    }

    m_statsTimer.setInterval(1000);
    connect(&m_statsTimer, &QTimer::timeout, this, &GstRunner::tick);
}

GstRunner::~GstRunner() {
    if (m_pipeline) {
        gst_element_set_state(m_pipeline, GST_STATE_NULL);
        if (m_recValve) gst_object_unref(m_recValve);
        gst_object_unref(m_pipeline);
    }
}

void GstRunner::play() {
    if (!m_pipeline) return;
    gst_element_set_state(m_pipeline, GST_STATE_PLAYING);
    m_statsTimer.start();
    m_lastStatsT = monoUs();
    m_frameCount = 0;
    m_byteCount = 0;
}

void GstRunner::stop() {
    if (!m_pipeline) return;
    m_statsTimer.stop();
    gst_element_set_state(m_pipeline, GST_STATE_NULL);
    if (m_linked) {
        m_linked = false;
        emit linkChanged(false);
    }
    emit fpsChanged(0.0);
    emit bitrateChanged(0.0);
}

GstFlowReturn GstRunner::onNewSampleCb(GstAppSink *s, gpointer u) {
    return static_cast<GstRunner *>(u)->onNewSample(s);
}
GstFlowReturn GstRunner::onInfSampleCb(GstAppSink *s, gpointer u) {
    return static_cast<GstRunner *>(u)->onInfSample(s);
}
GstFlowReturn GstRunner::onRecSampleCb(GstAppSink *s, gpointer u) {
    return static_cast<GstRunner *>(u)->onRecSample(s);
}

GstFlowReturn GstRunner::onNewSample(GstAppSink *sink) {
    GstSample *sample = gst_app_sink_pull_sample(sink);
    if (!sample) return GST_FLOW_OK;
    GstBuffer *buf = gst_sample_get_buffer(sample);
    GstCaps *caps = gst_sample_get_caps(sample);
    GstStructure *st = gst_caps_get_structure(caps, 0);
    int w = 0, h = 0;
    gst_structure_get_int(st, "width", &w);
    gst_structure_get_int(st, "height", &h);
    gsize size = gst_buffer_get_size(buf);

    GstMapInfo map;
    if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
        // BGRx 4 bytes/pixel; QImage RGB32 matches BGRx memory layout on LE.
        // Construct over the mapped data then deep-copy before unmap.
        QImage img(map.data, w, h, w * 4, QImage::Format_RGB32);
        QImage copy = img.copy();
        gst_buffer_unmap(buf, &map);
        emit frameReady(copy);
    }

    // latency (lag) estimate using pipeline running-time vs buffer pts
    GstClockTime pts = GST_BUFFER_PTS(buf);
    if (GST_CLOCK_TIME_IS_VALID(pts)) {
        GstClock *clock = gst_element_get_clock(m_pipeline);
        if (clock) {
            GstClockTime nowRunning =
                gst_clock_get_time(clock) - gst_element_get_base_time(m_pipeline);
            gst_object_unref(clock);
            gint64 lag = (gint64)nowRunning - (gint64)pts;
            if (lag > 0 && lag < 10000000000LL) {
                m_lagSumNs += (quint64)lag;
                m_lagN += 1;
            }
        }
    }
    m_frameCount += 1;
    m_byteCount += size;
    gst_sample_unref(sample);
    return GST_FLOW_OK;
}

GstFlowReturn GstRunner::onInfSample(GstAppSink *sink) {
    // Throttle to every DETECTION_INTERVAL_FRAMES; discard skipped to free buffer.
    m_inferSkip += 1;
    if (m_inferSkip < cfg::DETECTION_INTERVAL_FRAMES) {
        GstSample *s = gst_app_sink_pull_sample(sink);
        if (s) gst_sample_unref(s);
        return GST_FLOW_OK;
    }
    m_inferSkip = 0;
    GstSample *sample = gst_app_sink_pull_sample(sink);
    if (!sample) return GST_FLOW_OK;
    GstBuffer *buf = gst_sample_get_buffer(sample);
    GstMapInfo map;
    if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
        // 320x320 BGR (PXP HW resized). Deep-copy raw BGR bytes for the worker.
        QByteArray bgr(reinterpret_cast<const char *>(map.data),
                       (int)map.size);
        gst_buffer_unmap(buf, &map);
        emit rawReady(bgr);
    }
    gst_sample_unref(sample);
    return GST_FLOW_OK;
}

GstFlowReturn GstRunner::onRecSample(GstAppSink *sink) {
    GstSample *sample = gst_app_sink_pull_sample(sink);
    if (!sample) return GST_FLOW_OK;
    GstBuffer *buf = gst_sample_get_buffer(sample);
    GstMapInfo map;
    if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
        QMutexLocker lk(&m_recLock);
        if (m_recFile) {
            size_t wrote = std::fwrite(map.data, 1, map.size, m_recFile);
            m_recBytes += (qint64)wrote;
        }
        gst_buffer_unmap(buf, &map);
    }
    gst_sample_unref(sample);
    return GST_FLOW_OK;
}

void GstRunner::tick() {
    qint64 now = monoUs();
    double dt = (now - m_lastStatsT) / 1e6;
    if (dt <= 0) return;
    quint64 frames = m_frameCount.exchange(0);
    quint64 bytes = m_byteCount.exchange(0);
    quint64 lagSum = m_lagSumNs.exchange(0);
    quint64 lagN = m_lagN.exchange(0);
    m_lastStatsT = now;

    double fps = frames / dt;
    double mbps = bytes * 8.0 / 1e6 / dt;
    if (lagN > 0) {
        double lagMs = (double)lagSum / lagN / 1e6;
        emit latencyChanged(cfg::jitterBufferMs() + lagMs + 16);
    }
    bool linked = fps > 1.0;
    if (linked != m_linked) {
        m_linked = linked;
        emit linkChanged(linked);
    }
    emit fpsChanged(fps);
    emit bitrateChanged(mbps);
    if (cfg::logFps())
        qInfo("[FPS] display=%.2f mbps=%.2f", fps, mbps);
}

// ---- recording ----
bool GstRunner::startRecording(const QString &path) {
    {
        QMutexLocker lk(&m_recLock);
        if (m_recFile) return false;
        m_recFile = std::fopen(path.toLocal8Bit().constData(), "wb");
        if (!m_recFile) return false;
        std::setvbuf(m_recFile, nullptr, _IOFBF, 64 * 1024);
        m_recPath = path;
        m_recBytes = 0;
        m_recStartT = monoUs();
    }
    if (m_recValve)
        g_object_set(m_recValve, "drop", FALSE, nullptr);
    return true;
}

bool GstRunner::stopRecording(QString *path, qint64 *nBytes, double *durationS) {
    if (m_recValve)
        g_object_set(m_recValve, "drop", TRUE, nullptr);
    QMutexLocker lk(&m_recLock);
    if (!m_recFile) return false;
    std::fflush(m_recFile);
    std::fclose(m_recFile);
    if (path) *path = m_recPath;
    if (nBytes) *nBytes = m_recBytes;
    if (durationS) *durationS = (monoUs() - m_recStartT) / 1e6;
    m_recFile = nullptr;
    m_recPath.clear();
    m_recBytes = 0;
    return true;
}
