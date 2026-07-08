#include "Detector.h"
#ifdef HAVE_TFLITE
#include "Config.h"

#include <algorithm>
#include <cstring>
#include <stdexcept>
#include <vector>

namespace {
struct Cand { float x0, y0, x1, y1, score; int cls; };

float iou(const Cand &a, const Cand &b) {
    float ix0 = std::max(a.x0, b.x0), iy0 = std::max(a.y0, b.y0);
    float ix1 = std::min(a.x1, b.x1), iy1 = std::min(a.y1, b.y1);
    float iw = std::max(0.0f, ix1 - ix0), ih = std::max(0.0f, iy1 - iy0);
    float inter = iw * ih;
    float ua = (a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter;
    return ua > 0 ? inter / ua : 0.0f;
}
} // namespace

Detector::Detector() {
    m_model = TfLiteModelCreateFromFile(cfg::DETECTION_MODEL);
    if (!m_model)
        throw std::runtime_error("Detector: cannot load model");

    m_opts = TfLiteInterpreterOptionsCreate();

    // Ethos-U external delegate (libethosu_delegate.so via tflite_plugin_create_delegate)
    TfLiteExternalDelegateOptions ext =
        TfLiteExternalDelegateOptionsDefault(cfg::ETHOSU_DELEGATE);
    m_delegate = TfLiteExternalDelegateCreate(&ext);
    if (m_delegate)
        TfLiteInterpreterOptionsAddDelegate(m_opts, m_delegate);

    m_interp = TfLiteInterpreterCreate(m_model, m_opts);
    if (!m_interp)
        throw std::runtime_error("Detector: cannot create interpreter");
    if (TfLiteInterpreterAllocateTensors(m_interp) != kTfLiteOk)
        throw std::runtime_error("Detector: AllocateTensors failed");

    const TfLiteTensor *in = TfLiteInterpreterGetInputTensor(m_interp, 0);
    const TfLiteTensor *out = TfLiteInterpreterGetOutputTensor(m_interp, 0);
    m_inH = TfLiteTensorDim(in, 1);
    m_inW = TfLiteTensorDim(in, 2);
    TfLiteQuantizationParams q = TfLiteTensorQuantizationParams(out);
    m_outScale = q.scale;
    m_outZp = q.zero_point;
    qInfo("YOLO model loaded (C API): in %dx%d, out scale=%f zp=%d",
          m_inW, m_inH, m_outScale, m_outZp);
}

Detector::~Detector() {
    if (m_interp) TfLiteInterpreterDelete(m_interp);
    if (m_delegate) TfLiteExternalDelegateDelete(m_delegate);
    if (m_opts) TfLiteInterpreterOptionsDelete(m_opts);
    if (m_model) TfLiteModelDelete(m_model);
}

DetectionList Detector::infer(const QByteArray &bgr320) {
    DetectionList result;
    if (bgr320.size() < m_inW * m_inH * 3)
        return result;

    TfLiteTensor *in = TfLiteInterpreterGetInputTensor(m_interp, 0);
    int8_t *inp = reinterpret_cast<int8_t *>(TfLiteTensorData(in));
    const uint8_t *bgr = reinterpret_cast<const uint8_t *>(bgr320.constData());
    const int n = m_inW * m_inH;
    // BGR uint8 -> RGB int8 (value - 128), matching the Python preprocessing
    for (int i = 0; i < n; ++i) {
        inp[i * 3 + 0] = (int8_t)((int)bgr[i * 3 + 2] - 128);  // R
        inp[i * 3 + 1] = (int8_t)((int)bgr[i * 3 + 1] - 128);  // G
        inp[i * 3 + 2] = (int8_t)((int)bgr[i * 3 + 0] - 128);  // B
    }

    if (TfLiteInterpreterInvoke(m_interp) != kTfLiteOk)
        return result;

    const TfLiteTensor *out = TfLiteInterpreterGetOutputTensor(m_interp, 0);
    const int8_t *raw = reinterpret_cast<const int8_t *>(TfLiteTensorData(out));
    // shape (1, 9, A): channel-major -> raw[c*A + a]
    const int A = TfLiteTensorDim(out, 2);
    const int NCLS = (int)cfg::ANIMAL_LABELS.size();

    auto deq = [&](int idx) { return ((float)raw[idx] - m_outZp) * m_outScale; };

    std::vector<Cand> cands;
    cands.reserve(16);
    for (int a = 0; a < A; ++a) {
        int bestC = 0; float bestS = -1e9f;
        for (int c = 0; c < NCLS; ++c) {
            float s = deq((4 + c) * A + a);
            if (s > bestS) { bestS = s; bestC = c; }
        }
        if (bestS <= cfg::DETECTION_SCORE_THRESHOLD)
            continue;
        float cx = deq(0 * A + a), cy = deq(1 * A + a);
        float w = deq(2 * A + a), h = deq(3 * A + a);
        Cand cd;
        cd.x0 = cx - w / 2; cd.y0 = cy - h / 2;
        cd.x1 = cx + w / 2; cd.y1 = cy + h / 2;
        cd.score = bestS; cd.cls = bestC;
        cands.push_back(cd);
    }
    if (cands.empty()) return result;

    // greedy NMS (class-agnostic, matching cv2.dnn.NMSBoxes default)
    std::sort(cands.begin(), cands.end(),
              [](const Cand &a, const Cand &b) { return a.score > b.score; });
    std::vector<bool> removed(cands.size(), false);
    for (size_t i = 0; i < cands.size(); ++i) {
        if (removed[i]) continue;
        for (size_t j = i + 1; j < cands.size(); ++j)
            if (!removed[j] && iou(cands[i], cands[j]) > cfg::NMS_IOU_THRESHOLD)
                removed[j] = true;
    }

    for (size_t i = 0; i < cands.size() && result.size() < MAX_DETS; ++i) {
        if (removed[i]) continue;
        const Cand &c = cands[i];
        Detection d;
        d.x0 = std::clamp(c.x0, 0.0f, 1.0f);
        d.y0 = std::clamp(c.y0, 0.0f, 1.0f);
        d.x1 = std::clamp(c.x1, 0.0f, 1.0f);
        d.y1 = std::clamp(c.y1, 0.0f, 1.0f);
        d.label = cfg::ANIMAL_LABELS[c.cls];
        d.score = c.score;
        result.push_back(d);
    }
    return result;
}

#endif // HAVE_TFLITE
