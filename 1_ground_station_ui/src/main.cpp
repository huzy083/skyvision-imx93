#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QtQml>
#include <QTimer>
#include <QFile>
#include <QJsonObject>
#include <gst/gst.h>

#include <QQuickWindow>

#include "VideoItem.h"
#include "AppController.h"
#include "WifiManager.h"
#include "MqttPublisher.h"
#include "CameraManager.h"
#include "BatteryMonitor.h"
#include "ScreenRecorder.h"
#include "Config.h"

// Faithful port of skyvision_ui.py main(). The QML front-end is loaded from
// disk (same files the Python app used) so it stays the single source of truth.
int main(int argc, char *argv[]) {
    if (qgetenv("QT_QPA_PLATFORM").isEmpty()) qputenv("QT_QPA_PLATFORM", "wayland");
    if (qgetenv("QT_QUICK_BACKEND").isEmpty()) qputenv("QT_QUICK_BACKEND", "software");
    if (qgetenv("XDG_RUNTIME_DIR").isEmpty()) qputenv("XDG_RUNTIME_DIR", "/run/user/0");
    if (qgetenv("WAYLAND_DISPLAY").isEmpty()) qputenv("WAYLAND_DISPLAY", "wayland-0");

    gst_init(&argc, &argv);
    QGuiApplication app(argc, argv);
    QQuickStyle::setStyle("Basic");

    qRegisterMetaType<DetectionList>("DetectionList");
    qmlRegisterType<VideoItem>("SkyVision", 1, 0, "VideoItem");

    AppController controller;
    WifiManager wifi;
    MqttPublisher mqtt(cfg::mqttHost(), cfg::mqttPort());
    BatteryMonitor battery;
    // low-battery crossing -> UI event feed (which also relays to MQTT)
    QObject::connect(&battery, &BatteryMonitor::lowBattery,
                     &controller, &AppController::emitEvent);

    // forward UI/system events to MQTT
    QObject::connect(&controller, &AppController::event,
                     &mqtt, [&mqtt](const QString &msg, const QString &level) {
                         mqtt.publishEvent(msg, level);
                     });
    // bridge MQTT subscriber thread -> controller (queued onto GUI thread)
    QObject::connect(&mqtt, &MqttPublisher::linkStatsReceived,
                     &controller, &AppController::updateLinkStats, Qt::QueuedConnection);
    QObject::connect(&mqtt, &MqttPublisher::diagnosisReceived,
                     &controller, &AppController::addDiagnosisEvent, Qt::QueuedConnection);

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty("appCtl", &controller);
    engine.rootContext()->setContextProperty("wifiMgr", &wifi);
    engine.rootContext()->setContextProperty("batt", &battery);

    const QString qmlDir = cfg::envStr("SKYVISION_QML_DIR", "/root/ui-qml");
    const QString qmlPath = qmlDir + "/qml/Main.qml";
    engine.load(QUrl::fromLocalFile(qmlPath));
    if (engine.rootObjects().isEmpty()) {
        qCritical("ERROR: failed to load %s", qPrintable(qmlPath));
        return -1;
    }

    QObject *root = engine.rootObjects().first();
    auto *videoItem = root->findChild<VideoItem *>("videoItem");
    if (!videoItem) {
        qCritical("ERROR: videoItem not found in QML tree");
        return 2;
    }

    // 整屏录制(演示视频): 状态条"⏺ 录屏"按钮触发
    ScreenRecorder screenRec(&controller);
    screenRec.setWindow(qobject_cast<QQuickWindow *>(root));
    QObject::connect(&controller, &AppController::screenRecordRequested,
                     &screenRec, &ScreenRecorder::toggle);

    CameraManager camMgr(videoItem, &controller, &mqtt);
    QObject::connect(&controller, &AppController::cameraChanged,
                     &camMgr, [&] { camMgr.activate(controller.currentCamera()); });
    camMgr.activate(controller.currentCamera());

    // periodic status heartbeat
    QTimer statusTimer;
    QObject::connect(&statusTimer, &QTimer::timeout, [&] {
        mqtt.publishStatus(QJsonObject{
            {"camera", controller.currentCamera()},
            {"fps", qRound(controller.fps() * 100) / 100.0},
            {"latency_ms", qRound(controller.latencyMs() * 10) / 10.0},
            {"bitrate_mbps", qRound(controller.bitrateMbps() * 1000) / 1000.0},
            {"link", controller.linkStatus()},
            {"recording", controller.recording()},
            {"battery_pct", battery.valid() ? battery.percent() : -1},
            {"battery_v", qRound(battery.voltage() * 10) / 10.0},
        });
    });
    statusTimer.start(int(cfg::MQTT_STATUS_INTERVAL_S * 1000));

    // Signal the boot splash to stop covering /dev/fb0 after first paint.
    QTimer::singleShot(600, [] {
        QFile f("/run/skyvision-splash-done");
        f.open(QIODevice::WriteOnly);
        f.close();
    });

    int rc = app.exec();
    camMgr.stopAll();
    mqtt.stop();
    return rc;
}
