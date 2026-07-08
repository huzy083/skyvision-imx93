#pragma once
#include "Detection.h"
#ifdef HAVE_TFLITE
#include "Detector.h"
#include <QObject>
#include <QByteArray>
#include <thread>
#include <mutex>
#include <condition_variable>

// Runs NPU inference in a background thread; only keeps the latest frame.
// Faithful port of Python InferenceWorker.
class InferenceWorker : public QObject {
    Q_OBJECT
public:
    explicit InferenceWorker(Detector *detector, QObject *parent = nullptr);
    ~InferenceWorker() override;

    // newest overwrites — stale frames dropped (called from GStreamer thread)
    void submit(const QByteArray &bgr320);
    void stop();

signals:
    void detectionsReady(const DetectionList &dets);

private:
    void loop();

    Detector *m_detector;
    QByteArray m_latest;
    bool m_hasLatest = false;
    bool m_stop = false;
    std::mutex m_mtx;
    std::condition_variable m_cv;
    std::thread m_thread;
};
#endif // HAVE_TFLITE
