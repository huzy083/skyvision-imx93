#pragma once
#include "Detection.h"
#include <QObject>
#include <QString>
#include <QJsonObject>

// Async MQTT publisher/subscriber with auto-reconnect (libmosquitto).
// Compiled only when HAVE_MOSQUITTO is defined; otherwise a no-op stub so the
// rest of the app builds without the broker dependency.
#ifdef HAVE_MOSQUITTO
struct mosquitto;
#endif

class MqttPublisher : public QObject {
    Q_OBJECT
public:
    MqttPublisher(const QString &host, int port, QObject *parent = nullptr);
    ~MqttPublisher() override;

    void publishDetection(const QString &camera, const DetectionList &dets);
    void publishEvent(const QString &msg, const QString &level = "info",
                      const QJsonObject &extra = {});
    void publishStatus(const QJsonObject &stats);
    void stop();

signals:
    // Emitted from the mosquitto network thread (use queued connections).
    void linkStatsReceived(const QJsonObject &payload);
    void diagnosisReceived(const QJsonObject &payload);

private:
#ifdef HAVE_MOSQUITTO
    void publishJson(const char *topic, const QJsonObject &obj, int qos, bool retain);
    static void onConnectCb(struct mosquitto *m, void *u, int rc);
    static void onMessageCb(struct mosquitto *m, void *u, const struct mosquitto_message *msg);

    struct mosquitto *m_client = nullptr;
    QString m_host;
    int m_port;
    bool m_connected = false;
    double m_lastDetPub = 0.0;   // monotonic seconds
#endif
};
