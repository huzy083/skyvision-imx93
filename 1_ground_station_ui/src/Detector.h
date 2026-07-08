#pragma once
#include "Detection.h"
#include <QByteArray>

// YOLOv8n int8 (Vela-compiled) + Ethos-U65 NPU, 5-class animal model.
// Uses the TensorFlow Lite *C API* (libtensorflow-lite.so on the i.MX93 BSP
// exports it) — far lighter to build against than the C++ Interpreter headers
// (no flatbuffers/abseil needed). Compiled only when HAVE_TFLITE is defined.
#ifdef HAVE_TFLITE

#include <tensorflow/lite/c/c_api.h>
#include <tensorflow/lite/delegates/external/external_delegate.h>

class Detector {
public:
    static constexpr int MAX_DETS = 5;
    Detector();          // throws std::runtime_error on load failure
    ~Detector();

    // bgr320: 320*320*3 bytes, BGR (as delivered by the PXP inference branch).
    DetectionList infer(const QByteArray &bgr320);

private:
    TfLiteModel *m_model = nullptr;
    TfLiteInterpreterOptions *m_opts = nullptr;
    TfLiteInterpreter *m_interp = nullptr;
    TfLiteDelegate *m_delegate = nullptr;
    int m_inH = 320, m_inW = 320;
    float m_outScale = 1.0f;
    int m_outZp = 0;
};

#endif // HAVE_TFLITE
