#pragma once
#include <QObject>
#include <QVariantList>
#include <QString>
#include <QTimer>

// wpa_cli subprocess wrapper exposed to QML. Faithful port of wifi_manager.py.
// Property/slot names kept identical (networks/currentSSID/wpaState/busy,
// scan()/connectTo()/disconnect_()) so WiFiModal.qml is unchanged.
class WifiManager : public QObject {
    Q_OBJECT
    Q_PROPERTY(QVariantList networks READ networks NOTIFY networksChanged)
    Q_PROPERTY(QVariantList savedSSIDs READ savedSSIDs NOTIFY savedChanged)
    Q_PROPERTY(QString currentSSID READ currentSSID NOTIFY statusChanged)
    Q_PROPERTY(QString wpaState READ wpaState NOTIFY statusChanged)
    Q_PROPERTY(bool busy READ busy NOTIFY busyChanged)
public:
    explicit WifiManager(QObject *parent = nullptr);

    QVariantList networks() const { return m_networks; }
    QVariantList savedSSIDs() const { return m_savedSsids; }
    QString currentSSID() const { return m_currentSsid; }
    QString wpaState() const { return m_wpaState; }
    bool busy() const { return m_busy; }

public slots:
    void scan();
    void connectTo(const QString &ssid, const QString &password);
    void disconnect_(const QString &ssid);

signals:
    void networksChanged();
    void savedChanged();
    void statusChanged();
    void busyChanged();

private:
    static QString wpa(const QStringList &args, int timeoutMs = 4000);
    void setBusy(bool v);
    void refreshStatus();
    void refreshSaved();
    void collectScan();
    void postConnect();

    QVariantList m_networks;
    QVariantList m_savedSsids;
    QString m_currentSsid;
    QString m_wpaState;
    bool m_busy = false;
    QTimer m_pollTimer;
};
