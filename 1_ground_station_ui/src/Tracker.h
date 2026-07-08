#pragma once
#include "Detection.h"
#include <QVector>
#include <QPointF>
#include <QString>

// Lightweight IOU/SORT-style multi-object tracker.
//
// WHY (power-inspection context): the UAV moves past STATIC assets (insulators,
// dampers, bird-nests), so the same physical component appears in many frames.
// Per-frame detection alone would count/alert on it repeatedly. Assigning a
// persistent track ID lets us (a) count each asset once, (b) emit each defect
// event once (dedup), (c) bridge one-frame misses (jitter/occlusion recovery),
// and (d) draw a trajectory. No motion model — at 15fps the last bbox is a good
// enough predictor, and IOU is scale-invariant so it tolerates the zoom from
// approach. All coordinates are normalized [0,1] (same as Detection).
struct Track {
    int      id = 0;
    QString  label;
    float    x0 = 0, y0 = 0, x1 = 0, y1 = 0;  // last matched bbox (normalized)
    float    score = 0;
    int      hits = 0;        // total frames matched
    int      missed = 0;      // consecutive frames without a match
    bool     confirmed = false;   // survived >= minHits — a real object
    bool     reported = false;    // defect event already emitted for this track
    QVector<QPointF> trail;   // recent normalized centers, for drawing the path

    QPointF center() const { return QPointF((x0 + x1) * 0.5, (y0 + y1) * 0.5); }
};

class Tracker {
public:
    // Advance one frame with the current detections; returns the live tracks
    // (confirmed and tentative) with stable IDs. Call once per inference result.
    QVector<Track> update(const DetectionList &dets);

    void reset() { m_tracks.clear(); m_nextId = 1; }

    // Tunables (frame-rate dependent; defaults suit ~7-15 detections/s).
    float iouThresh = 0.30f;  // min IOU to associate a detection with a track
    int   maxMissed = 15;     // drop a track after this many consecutive misses
    int   minHits   = 3;      // confirm a track after this many hits
    int   maxTrail  = 24;     // trajectory point cap

private:
    static float iou(const Detection &d, const Track &t);

    QVector<Track> m_tracks;
    int m_nextId = 1;
};
