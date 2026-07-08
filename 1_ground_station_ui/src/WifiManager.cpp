#include "WifiManager.h"
#include <QProcess>
#include <QVariantMap>
#include <QSet>
#include <algorithm>

static const char *WIFI_IFACE = "mlan0";
static const char *WPA_CLI = "/usr/sbin/wpa_cli";

QString WifiManager::wpa(const QStringList &args, int timeoutMs) {
    QProcess proc;
    QStringList full;
    full << "-i" << WIFI_IFACE << args;
    proc.start(WPA_CLI, full);
    if (!proc.waitForStarted(timeoutMs))
        return QStringLiteral("ERR: start");
    if (!proc.waitForFinished(timeoutMs)) {
        proc.kill();
        return QStringLiteral("ERR: timeout");
    }
    return QString::fromUtf8(proc.readAllStandardOutput());
}

WifiManager::WifiManager(QObject *parent) : QObject(parent) {
    refreshSaved();
    refreshStatus();
    m_pollTimer.setInterval(3000);
    connect(&m_pollTimer, &QTimer::timeout, this, &WifiManager::refreshStatus);
    m_pollTimer.start();
}

void WifiManager::setBusy(bool v) {
    if (v != m_busy) {
        m_busy = v;
        emit busyChanged();
    }
}

void WifiManager::refreshSaved() {
    QString out = wpa({"list_networks"});
    QVariantList ss;
    const QStringList lines = out.split('\n');
    for (int i = 1; i < lines.size(); ++i) {
        const QStringList parts = lines[i].split('\t');
        if (parts.size() >= 2 && !parts[1].isEmpty())
            ss.append(parts[1]);
    }
    if (ss != m_savedSsids) {
        m_savedSsids = ss;
        emit savedChanged();
    }
}

void WifiManager::refreshStatus() {
    QString out = wpa({"status"});
    QString ssid, state;
    for (const QString &line : out.split('\n')) {
        if (line.startsWith("ssid="))
            ssid = line.mid(5);
        else if (line.startsWith("wpa_state="))
            state = line.mid(10);
    }
    if (ssid != m_currentSsid || state != m_wpaState) {
        m_currentSsid = ssid;
        m_wpaState = state;
        emit statusChanged();
    }
}

void WifiManager::scan() {
    setBusy(true);
    wpa({"scan"});
    QTimer::singleShot(2500, this, &WifiManager::collectScan);
}

void WifiManager::collectScan() {
    QString out = wpa({"scan_results"});
    QVariantList nets;
    QSet<QString> seen;
    const QStringList lines = out.split('\n');
    for (int i = 1; i < lines.size(); ++i) {
        const QStringList parts = lines[i].split('\t');
        if (parts.size() < 5)
            continue;
        const QString bssid = parts[0], freq = parts[1], sig = parts[2],
                      flags = parts[3], ssid = parts[4];
        if (ssid.isEmpty() || seen.contains(ssid))
            continue;
        seen.insert(ssid);
        bool secured = flags.contains("PSK") || flags.contains("WEP") || flags.contains("EAP");
        bool ok = false;
        int sigInt = sig.toInt(&ok);
        if (!ok) sigInt = -100;
        nets.append(QVariantMap{
            {"ssid", ssid}, {"bssid", bssid}, {"freq", freq},
            {"signal", sigInt}, {"secured", secured},
        });
    }
    std::sort(nets.begin(), nets.end(), [](const QVariant &a, const QVariant &b) {
        return a.toMap()["signal"].toInt() > b.toMap()["signal"].toInt();
    });
    m_networks = nets;
    emit networksChanged();
    setBusy(false);
}

void WifiManager::connectTo(const QString &ssid, const QString &password) {
    setBusy(true);
    QString out = wpa({"list_networks"});
    QString netId;
    const QStringList lines = out.split('\n');
    for (int i = 1; i < lines.size(); ++i) {
        const QStringList parts = lines[i].split('\t');
        if (parts.size() >= 2 && parts[1] == ssid) {
            netId = parts[0];
            break;
        }
    }
    if (netId.isEmpty()) {
        QString r = wpa({"add_network"}).trimmed();
        bool ok = false; r.toInt(&ok);
        if (!ok) { setBusy(false); return; }
        netId = r;
        wpa({"set_network", netId, "ssid", QString("\"%1\"").arg(ssid)});
        if (!password.isEmpty())
            wpa({"set_network", netId, "psk", QString("\"%1\"").arg(password)});
        else
            wpa({"set_network", netId, "key_mgmt", "NONE"});
    } else if (!password.isEmpty()) {
        wpa({"set_network", netId, "psk", QString("\"%1\"").arg(password)});
    }
    wpa({"enable_network", netId});
    wpa({"select_network", netId});
    wpa({"save_config"});
    QTimer::singleShot(500, this, &WifiManager::refreshSaved);
    QTimer::singleShot(4000, this, &WifiManager::postConnect);
}

void WifiManager::postConnect() {
    QProcess::startDetached("/sbin/udhcpc",
                            {"-i", WIFI_IFACE, "-q", "-n", "-t", "5"});
    QTimer::singleShot(2000, this, &WifiManager::refreshStatus);
    QTimer::singleShot(2500, this, [this] { setBusy(false); });
}

void WifiManager::disconnect_(const QString &ssid) {
    QString out = wpa({"list_networks"});
    const QStringList lines = out.split('\n');
    for (int i = 1; i < lines.size(); ++i) {
        const QStringList parts = lines[i].split('\t');
        if (parts.size() >= 2 && parts[1] == ssid) {
            wpa({"disable_network", parts[0]});
            break;
        }
    }
    wpa({"disconnect"});
    refreshStatus();
}
