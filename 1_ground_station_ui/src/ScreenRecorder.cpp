#include "ScreenRecorder.h"
#include "AppController.h"
#include "Config.h"
#include <QQuickWindow>
#include <QImage>
#include <QDir>
#include <QFileInfo>
#include <QDateTime>
#include <gst/app/gstappsrc.h>

// 视频流~20fps, 录屏要跟上才不掉演示细节; 太卡可用环境变量降
static const int SCREEN_FPS = cfg::envInt("SKYVISION_SCREENREC_FPS", 20);

ScreenRecorder::ScreenRecorder(AppController *ctl, QObject *parent)
    : QObject(parent), m_ctl(ctl) {
    m_timer.setInterval(1000 / SCREEN_FPS);
    m_timer.setTimerType(Qt::PreciseTimer);
    connect(&m_timer, &QTimer::timeout, this, &ScreenRecorder::tick);
}

ScreenRecorder::~ScreenRecorder() {
    if (m_pipe) stop();
}

void ScreenRecorder::toggle() {
    if (m_pipe) {
        stop();
        return;
    }
    if (start())
        m_ctl->setScreenRecording(true);
}

bool ScreenRecorder::start() {
    if (!m_win) {
        m_ctl->emitEvent("录屏失败: 窗口未就绪", "warn");
        return false;
    }
    QImage probe = m_win->grabWindow();
    if (probe.isNull()) {
        m_ctl->emitEvent("录屏失败: 抓屏为空", "warn");
        return false;
    }
    m_w = probe.width();
    m_h = probe.height();

    QString ts = QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss");
    m_path = QDir(cfg::recordingsDir()).filePath(QString("screen_%1.avi").arg(ts));
    QString desc = QString(
        "appsrc name=src is-live=true format=time "
        "caps=video/x-raw,format=BGRx,width=%1,height=%2,framerate=%3/1 ! "
        "videoconvert ! video/x-raw,format=I420 ! "   // 强制YUV: RGB-JPEG太偏门(pxp/部分播放器不认)
        "jpegenc quality=80 ! avimux ! filesink location=\"%4\"")
        .arg(m_w).arg(m_h).arg(SCREEN_FPS).arg(m_path);

    GError *err = nullptr;
    m_pipe = gst_parse_launch(desc.toUtf8().constData(), &err);
    if (!m_pipe) {
        m_ctl->emitEvent(QString("录屏失败: %1").arg(err ? err->message : "pipeline"), "warn");
        if (err) g_error_free(err);
        return false;
    }
    if (err) g_error_free(err);
    m_src = gst_bin_get_by_name(GST_BIN(m_pipe), "src");
    gst_element_set_state(m_pipe, GST_STATE_PLAYING);
    m_frames = 0;
    m_timer.start();
    m_ctl->emitEvent(QString("开始录屏 %1x%2@%3fps").arg(m_w).arg(m_h).arg(SCREEN_FPS), "info");
    return true;
}

void ScreenRecorder::tick() {
    if (!m_pipe || !m_win) return;
    QImage img = m_win->grabWindow().convertToFormat(QImage::Format_RGB32);
    if (img.isNull() || img.width() != m_w || img.height() != m_h)
        return;   // 窗口尺寸变化的帧直接丢
    const qsizetype nbytes = img.sizeInBytes();
    GstBuffer *buf = gst_buffer_new_allocate(nullptr, nbytes, nullptr);
    gst_buffer_fill(buf, 0, img.constBits(), nbytes);
    GST_BUFFER_PTS(buf) = gst_util_uint64_scale(m_frames, GST_SECOND, SCREEN_FPS);
    GST_BUFFER_DURATION(buf) = gst_util_uint64_scale(1, GST_SECOND, SCREEN_FPS);
    m_frames++;
    gst_app_src_push_buffer(GST_APP_SRC(m_src), buf);   // takes ownership
}

void ScreenRecorder::stop() {
    m_timer.stop();
    if (!m_pipe) return;
    gst_app_src_end_of_stream(GST_APP_SRC(m_src));
    // 等 avimux 写完索引(EOS 走完管线), 5s 兜底
    GstBus *bus = gst_element_get_bus(m_pipe);
    GstMessage *msg = gst_bus_timed_pop_filtered(
        bus, 5 * GST_SECOND,
        (GstMessageType)(GST_MESSAGE_EOS | GST_MESSAGE_ERROR));
    if (msg) gst_message_unref(msg);
    gst_object_unref(bus);
    gst_element_set_state(m_pipe, GST_STATE_NULL);
    gst_object_unref(m_src);
    m_src = nullptr;
    gst_object_unref(m_pipe);
    m_pipe = nullptr;
    m_ctl->setScreenRecording(false);
    m_ctl->emitEvent(QString("录屏已保存: %1 (%2s)")
                         .arg(QFileInfo(m_path).fileName())
                         .arg(double(m_frames) / SCREEN_FPS, 0, 'f', 1), "info");
}
