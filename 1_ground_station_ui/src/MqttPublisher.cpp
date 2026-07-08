#include "MqttPublisher.h"
#include "Config.h"
#include <QJsonDocument>
#include <QJsonArray>
#include <QDateTime>
#include <QTimer>

#ifdef HAVE_MOSQUITTO
#include <mosquitto.h>
#include <unistd.h>
#include <chrono>

static double nowEpoch() {
    return QDateTime::currentMSecsSinceEpoch() / 1000.0;
}
static double monoSec() {
    using namespace std::chrono;
    return duration<double>(steady_clock::now().time_since_epoch()).count();
}

MqttPublisher::MqttPublisher(const QString &host, int port, QObject *parent)
    : QObject(parent), m_host(host), m_port(port) {
    mosquitto_lib_init();
    QByteArray cid = QString("skyvision-rx-%1").arg(getpid()).toUtf8();
    m_client = mosquitto_new(cid.constData(), true, this);
    if (!m_client) {
        qWarning("[MQTT] init failed");
        return;
    }
    mosquitto_reconnect_delay_set(m_client, 1, 30, false);
    if (!cfg::mqttUser().isEmpty()) {
        QByteArray u = cfg::mqttUser().toUtf8();
        QByteArray pw = cfg::mqttPass().toUtf8();
        mosquitto_username_pw_set(m_client, u.constData(),
                                  pw.isEmpty() ? nullptr : pw.constData());
    }
    mosquitto_connect_callback_set(m_client, &MqttPublisher::onConnectCb);
    mosquitto_message_callback_set(m_client, &MqttPublisher::onMessageCb);

    // last-will so subscribers know if we crash
    QJsonObject will{{"ts", nowEpoch()}, {"online", false}};
    QByteArray wp = QJsonDocument(will).toJson(QJsonDocument::Compact);
    mosquitto_will_set(m_client, cfg::TOPIC_STATUS, wp.size(), wp.constData(), 1, true);

    QByteArray h = host.toUtf8();
    if (mosquitto_connect_async(m_client, h.constData(), port, 30) == MOSQ_ERR_SUCCESS) {
        mosquitto_loop_start(m_client);
        qInfo("[MQTT] connecting to %s:%d", h.constData(), port);
    } else {
        // Initial connect can fail while the network/DNS is still coming up at
        // boot; keep retrying instead of staying dead until a UI restart.
        qWarning("[MQTT] connect_async failed, retrying every 10s");
        auto *t = new QTimer(this);
        connect(t, &QTimer::timeout, this, [this, t]() {
            QByteArray hh = m_host.toUtf8();
            if (mosquitto_connect_async(m_client, hh.constData(), m_port, 30) == MOSQ_ERR_SUCCESS) {
                mosquitto_loop_start(m_client);
                qInfo("[MQTT] connected on retry");
                t->stop();
                t->deleteLater();
            }
        });
        t->start(10000);
    }
}

MqttPublisher::~MqttPublisher() {
    stop();
    if (m_client) mosquitto_destroy(m_client);
    mosquitto_lib_cleanup();
}

void MqttPublisher::onConnectCb(struct mosquitto *m, void *u, int rc) {
    auto *self = static_cast<MqttPublisher *>(u);
    self->m_connected = (rc == 0);
    qInfo("[MQTT] on_connect rc=%d connected=%d", rc, self->m_connected);
    if (self->m_connected) {
        QJsonObject st{{"ts", nowEpoch()}, {"online", true}};
        QByteArray p = QJsonDocument(st).toJson(QJsonDocument::Compact);
        mosquitto_publish(m, nullptr, cfg::TOPIC_STATUS, p.size(), p.constData(), 1, true);
        mosquitto_subscribe(m, nullptr, cfg::TOPIC_LINK, 0);
        mosquitto_subscribe(m, nullptr, cfg::TOPIC_DIAGNOSIS, 0);
    }
}

void MqttPublisher::onMessageCb(struct mosquitto *, void *u,
                                const struct mosquitto_message *msg) {
    auto *self = static_cast<MqttPublisher *>(u);
    QByteArray payload((const char *)msg->payload, msg->payloadlen);
    QJsonParseError perr;
    QJsonDocument doc = QJsonDocument::fromJson(payload, &perr);
    if (perr.error != QJsonParseError::NoError || !doc.isObject())
        return;
    QString topic = QString::fromUtf8(msg->topic);
    if (topic == cfg::TOPIC_DIAGNOSIS)
        emit self->diagnosisReceived(doc.object());
    else if (topic == cfg::TOPIC_LINK)
        emit self->linkStatsReceived(doc.object());
}

void MqttPublisher::publishJson(const char *topic, const QJsonObject &obj,
                                int qos, bool retain) {
    if (!m_client) return;
    QByteArray p = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    mosquitto_publish(m_client, nullptr, topic, p.size(), p.constData(), qos, retain);
}

void MqttPublisher::publishDetection(const QString &camera, const DetectionList &dets) {
    if (!m_client) return;
    double now = monoSec();
    if (now - m_lastDetPub < cfg::MQTT_DETECTION_INTERVAL_S)
        return;
    m_lastDetPub = now;
    QJsonArray objs;
    for (const auto &d : dets) {
        objs.append(QJsonObject{
            {"label", d.label},
            {"score", qRound(d.score * 1000.0) / 1000.0},
            {"bbox", QJsonArray{
                qRound(d.x0 * 1000.0) / 1000.0, qRound(d.y0 * 1000.0) / 1000.0,
                qRound(d.x1 * 1000.0) / 1000.0, qRound(d.y1 * 1000.0) / 1000.0}},
            {"in_zone", d.inZone},
        });
    }
    publishJson(cfg::TOPIC_DETECTION,
                QJsonObject{{"ts", nowEpoch()}, {"camera", camera}, {"objects", objs}},
                0, false);
}

void MqttPublisher::publishEvent(const QString &msg, const QString &level,
                                 const QJsonObject &extra) {
    if (!m_client) return;
    QJsonObject o{{"ts", nowEpoch()}, {"level", level}, {"msg", msg}};
    for (auto it = extra.begin(); it != extra.end(); ++it)
        o.insert(it.key(), it.value());
    publishJson(cfg::TOPIC_EVENT, o, 1, false);
}

void MqttPublisher::publishStatus(const QJsonObject &stats) {
    if (!m_client) return;
    QJsonObject o{{"ts", nowEpoch()}, {"online", true}};
    for (auto it = stats.begin(); it != stats.end(); ++it)
        o.insert(it.key(), it.value());
    publishJson(cfg::TOPIC_STATUS, o, 0, true);
}

void MqttPublisher::stop() {
    if (!m_client) return;
    QJsonObject off{{"ts", nowEpoch()}, {"online", false}};
    QByteArray p = QJsonDocument(off).toJson(QJsonDocument::Compact);
    mosquitto_publish(m_client, nullptr, cfg::TOPIC_STATUS, p.size(), p.constData(), 1, true);
    mosquitto_loop_stop(m_client, true);
    mosquitto_disconnect(m_client);
}

#else // !HAVE_MOSQUITTO  -- no-op stub

MqttPublisher::MqttPublisher(const QString &, int, QObject *parent) : QObject(parent) {}
MqttPublisher::~MqttPublisher() {}
void MqttPublisher::publishDetection(const QString &, const DetectionList &) {}
void MqttPublisher::publishEvent(const QString &, const QString &, const QJsonObject &) {}
void MqttPublisher::publishStatus(const QJsonObject &) {}
void MqttPublisher::stop() {}

#endif
