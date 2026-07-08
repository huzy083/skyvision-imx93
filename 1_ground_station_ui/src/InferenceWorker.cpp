#include "InferenceWorker.h"
#ifdef HAVE_TFLITE

InferenceWorker::InferenceWorker(Detector *detector, QObject *parent)
    : QObject(parent), m_detector(detector) {
    m_thread = std::thread(&InferenceWorker::loop, this);
}

InferenceWorker::~InferenceWorker() {
    stop();
    if (m_thread.joinable())
        m_thread.join();
}

void InferenceWorker::submit(const QByteArray &bgr320) {
    {
        std::lock_guard<std::mutex> lk(m_mtx);
        m_latest = bgr320;   // newest overwrites
        m_hasLatest = true;
    }
    m_cv.notify_one();
}

void InferenceWorker::stop() {
    {
        std::lock_guard<std::mutex> lk(m_mtx);
        m_stop = true;
    }
    m_cv.notify_all();
}

void InferenceWorker::loop() {
    while (true) {
        QByteArray arr;
        {
            std::unique_lock<std::mutex> lk(m_mtx);
            m_cv.wait(lk, [this] { return m_stop || m_hasLatest; });
            if (m_stop) return;
            arr = m_latest;
            m_hasLatest = false;
        }
        try {
            DetectionList dets = m_detector->infer(arr);
            emit detectionsReady(dets);
        } catch (const std::exception &e) {
            qWarning("infer error: %s", e.what());
        }
    }
}

#endif // HAVE_TFLITE
