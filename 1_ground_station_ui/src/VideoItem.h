#pragma once
#include <QQuickPaintedItem>
#include <QImage>
#include <QPainter>

// Mirrors the Python VideoItem(QQuickPaintedItem): holds the latest decoded
// frame (with overlays already painted in) and blits it in paint().
class VideoItem : public QQuickPaintedItem {
    Q_OBJECT
public:
    explicit VideoItem(QQuickItem *parent = nullptr) : QQuickPaintedItem(parent) {
        setFillColor(Qt::black);
    }

    // Called from the GUI thread (CameraManager) with the frame to display.
    void setImage(const QImage &img) {
        m_image = img;
        update();
    }

    void paint(QPainter *painter) override {
        if (m_image.isNull())
            return;
        painter->drawImage(boundingRect().topLeft(), m_image);
    }

private:
    QImage m_image;
};
