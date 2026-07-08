#pragma once
#include <QString>
#include <QList>
#include <QMetaType>

// One detection box, normalized [0,1]. Mirrors the dict the Python detector
// produced ({x0,y0,x1,y1,label,score,in_zone}).
struct Detection {
    float x0 = 0, y0 = 0, x1 = 0, y1 = 0;
    QString label;
    float score = 0;
    bool inZone = false;
};
using DetectionList = QList<Detection>;
Q_DECLARE_METATYPE(Detection)
Q_DECLARE_METATYPE(DetectionList)
