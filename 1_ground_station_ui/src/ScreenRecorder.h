#pragma once
#include <QObject>
#include <QTimer>
#include <QString>
#include <gst/gst.h>

class QQuickWindow;
class AppController;

// 整屏录制(录演示视频用): 10fps QQuickWindow::grabWindow —— 软件渲染后端
// (QT_QUICK_BACKEND=software)下这是纯 CPU 拷贝, 不动 GPU —— 推进
// appsrc ! videoconvert ! jpegenc ! avimux, 存 recordings/screen_*.avi。
// 板上没有 H.264 编码器(无 VPU/x264), MJPEG 是唯一低成本选项, 文件偏大
// (~50MB/min)但任何播放器都能放。
class ScreenRecorder : public QObject {
    Q_OBJECT
public:
    explicit ScreenRecorder(AppController *ctl, QObject *parent = nullptr);
    ~ScreenRecorder() override;
    void setWindow(QQuickWindow *w) { m_win = w; }

public slots:
    void toggle();

private:
    void tick();
    bool start();
    void stop();

    AppController *m_ctl;
    QQuickWindow *m_win = nullptr;
    QTimer m_timer;
    GstElement *m_pipe = nullptr;
    GstElement *m_src = nullptr;
    QString m_path;
    int m_w = 0, m_h = 0;
    guint64 m_frames = 0;
};
