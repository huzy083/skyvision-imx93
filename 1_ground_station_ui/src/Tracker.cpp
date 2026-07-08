#include "Tracker.h"
#include <algorithm>

float Tracker::iou(const Detection &d, const Track &t) {
    const float ix0 = std::max(d.x0, t.x0), iy0 = std::max(d.y0, t.y0);
    const float ix1 = std::min(d.x1, t.x1), iy1 = std::min(d.y1, t.y1);
    const float iw = ix1 - ix0, ih = iy1 - iy0;
    if (iw <= 0 || ih <= 0) return 0.0f;
    const float inter = iw * ih;
    const float ad = std::max(0.0f, d.x1 - d.x0) * std::max(0.0f, d.y1 - d.y0);
    const float at = std::max(0.0f, t.x1 - t.x0) * std::max(0.0f, t.y1 - t.y0);
    const float uni = ad + at - inter;
    return uni > 0 ? inter / uni : 0.0f;
}

QVector<Track> Tracker::update(const DetectionList &dets) {
    const int nT = m_tracks.size();
    const int nD = dets.size();

    // 1) Candidate pairs: same label + IOU over threshold.
    struct Pair { float iou; int t; int d; };
    QVector<Pair> pairs;
    pairs.reserve(nT * nD);
    for (int ti = 0; ti < nT; ++ti)
        for (int di = 0; di < nD; ++di) {
            if (dets[di].label != m_tracks[ti].label) continue;
            const float s = iou(dets[di], m_tracks[ti]);
            if (s >= iouThresh) pairs.push_back({s, ti, di});
        }

    // 2) Greedy assignment, highest IOU first.
    std::sort(pairs.begin(), pairs.end(),
              [](const Pair &a, const Pair &b) { return a.iou > b.iou; });
    QVector<bool> tUsed(nT, false), dUsed(nD, false);
    for (const Pair &p : pairs) {
        if (tUsed[p.t] || dUsed[p.d]) continue;
        tUsed[p.t] = dUsed[p.d] = true;
        Track &t = m_tracks[p.t];
        const Detection &d = dets[p.d];
        t.x0 = d.x0; t.y0 = d.y0; t.x1 = d.x1; t.y1 = d.y1;
        t.score = d.score;
        t.hits += 1;
        t.missed = 0;
        if (!t.confirmed && t.hits >= minHits) t.confirmed = true;
        t.trail.push_back(t.center());
        while (t.trail.size() > maxTrail) t.trail.removeFirst();
    }

    // 3) Unmatched tracks age; drop the stale ones.
    for (int ti = 0; ti < nT; ++ti)
        if (!tUsed[ti]) m_tracks[ti].missed += 1;
    m_tracks.erase(std::remove_if(m_tracks.begin(), m_tracks.end(),
                       [&](const Track &t) { return t.missed > maxMissed; }),
                   m_tracks.end());

    // 4) Unmatched detections spawn tentative tracks.
    for (int di = 0; di < nD; ++di) {
        if (dUsed[di]) continue;
        const Detection &d = dets[di];
        Track t;
        t.id = m_nextId++;
        t.label = d.label;
        t.x0 = d.x0; t.y0 = d.y0; t.x1 = d.x1; t.y1 = d.y1;
        t.score = d.score;
        t.hits = 1;
        t.confirmed = (minHits <= 1);
        t.trail.push_back(t.center());
        m_tracks.push_back(t);
    }

    return m_tracks;
}
