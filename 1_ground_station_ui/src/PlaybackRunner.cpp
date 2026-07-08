#include "PlaybackRunner.h"
#include <string>

std::string PlaybackRunner::makePipeline(const QString &path) {
    const std::string p = path.toStdString();
    std::string src;
    // 不用 decodebin: 这块板上它优选 NXP aiurdemux, 对我们的 MJPEG AVI 直接
    // "general stream error"。全部走显式管线。
    if (path.endsWith(".h264"))
        src = "filesrc location=\"" + p + "\" ! h264parse ! "
              "avdec_h264 max-threads=2 thread-type=2 output-corrupt=false ";
    else if (path.endsWith(".avi"))
        // 录屏MJPEG; videoconvert兜住非常规像素格式(旧录屏是RGB-JPEG, pxp不认)
        src = "filesrc location=\"" + p + "\" ! avidemux ! jpegdec ! videoconvert ";
    else
        src = "filesrc location=\"" + p + "\" ! qtdemux ! h264parse ! "
              "avdec_h264 max-threads=2 thread-type=2 output-corrupt=false ";
    return src +
        "! imxvideoconvert_pxp ! "
        "video/x-raw,format=BGRx,width=960,height=600 ! "
        "appsink name=sink emit-signals=true max-buffers=2 drop=false sync=true";
}

PlaybackRunner::PlaybackRunner(const QString &path, QObject *parent)
    : QObject(parent), m_path(path) {
    GError *err = nullptr;
    m_pipeline = gst_parse_launch(makePipeline(path).c_str(), &err);
    if (!m_pipeline) {
        qWarning("PlaybackRunner: parse_launch failed: %s", err ? err->message : "(null)");
        if (err) g_error_free(err);
        return;
    }
    GstElement *sink = gst_bin_get_by_name(GST_BIN(m_pipeline), "sink");
    if (sink) {
        GstAppSinkCallbacks cb{};
        cb.new_sample = &PlaybackRunner::onNewSampleCb;
        gst_app_sink_set_callbacks(GST_APP_SINK(sink), &cb, this, nullptr);
        gst_object_unref(sink);
    }
    GstBus *bus = gst_element_get_bus(m_pipeline);
    m_busWatch = gst_bus_add_watch(bus, &PlaybackRunner::onBusCb, this);
    gst_object_unref(bus);
}

PlaybackRunner::~PlaybackRunner() {
    if (m_busWatch) g_source_remove(m_busWatch);
    if (m_pipeline) {
        gst_element_set_state(m_pipeline, GST_STATE_NULL);
        gst_object_unref(m_pipeline);
    }
}

void PlaybackRunner::play() {
    if (m_pipeline) gst_element_set_state(m_pipeline, GST_STATE_PLAYING);
}

void PlaybackRunner::stop() {
    if (m_pipeline) gst_element_set_state(m_pipeline, GST_STATE_NULL);
}

GstFlowReturn PlaybackRunner::onNewSampleCb(GstAppSink *s, gpointer u) {
    return static_cast<PlaybackRunner *>(u)->onNewSample(s);
}

GstFlowReturn PlaybackRunner::onNewSample(GstAppSink *sink) {
    GstSample *sample = gst_app_sink_pull_sample(sink);
    if (!sample) return GST_FLOW_OK;
    GstBuffer *buf = gst_sample_get_buffer(sample);
    GstCaps *caps = gst_sample_get_caps(sample);
    GstStructure *st = gst_caps_get_structure(caps, 0);
    int w = 0, h = 0;
    gst_structure_get_int(st, "width", &w);
    gst_structure_get_int(st, "height", &h);
    GstMapInfo map;
    if (gst_buffer_map(buf, &map, GST_MAP_READ)) {
        QImage img(map.data, w, h, w * 4, QImage::Format_RGB32);
        QImage copy = img.copy();
        gst_buffer_unmap(buf, &map);
        emit frameReady(copy);
    }
    gst_sample_unref(sample);
    return GST_FLOW_OK;
}

gboolean PlaybackRunner::onBusCb(GstBus *, GstMessage *msg, gpointer u) {
    auto *self = static_cast<PlaybackRunner *>(u);
    switch (GST_MESSAGE_TYPE(msg)) {
    case GST_MESSAGE_EOS:
        emit self->finished();
        break;
    case GST_MESSAGE_ERROR: {
        GError *err = nullptr; gchar *dbg = nullptr;
        gst_message_parse_error(msg, &err, &dbg);
        qWarning("playback err: %s", err ? err->message : "(null)");
        if (err) g_error_free(err);
        g_free(dbg);
        emit self->finished();
        break;
    }
    default: break;
    }
    return TRUE;
}
