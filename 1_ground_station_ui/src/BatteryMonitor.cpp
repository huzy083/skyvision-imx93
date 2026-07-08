#include "BatteryMonitor.h"
#include "Config.h"
#include <QFile>
#include <QByteArray>
#include <algorithm>

BatteryMonitor::BatteryMonitor(QObject *parent) : QObject(parent) {
    const QString dir = cfg::batIioDir();
    m_rawPath = QString("%1/in_voltage%2_raw").arg(dir).arg(cfg::BAT_ADC_CHANNEL);
    m_ratio   = (cfg::BAT_R_TOP + cfg::BAT_R_BOTTOM) / cfg::BAT_R_BOTTOM;  // 9.2
    m_cal     = cfg::batCal();
    m_cells   = std::max(1, cfg::batCells());
    m_warnPct = cfg::BAT_WARN_PCT;
    loadScale();

    m_timer.setInterval(int(cfg::BAT_POLL_S * 1000));
    connect(&m_timer, &QTimer::timeout, this, &BatteryMonitor::poll);
    m_timer.start();
    poll();  // first sample immediately
}

void BatteryMonitor::loadScale() {
    // in_voltage_scale is shared across channels on imx93-adc (mV/LSB).
    QFile f(cfg::batIioDir() + "/in_voltage_scale");
    if (f.open(QIODevice::ReadOnly)) {
        bool ok = false;
        double s = f.readAll().trimmed().toDouble(&ok);
        if (ok && s > 0) { m_scaleMv = s; return; }
    }
    m_scaleMv = cfg::BAT_SCALE_MV_FALLBACK;  // 1800/4096 for the 12-bit / 1.8V ADC
}

bool BatteryMonitor::readRaw(int &raw) const {
    QFile f(m_rawPath);
    if (!f.open(QIODevice::ReadOnly)) return false;
    bool ok = false;
    int v = f.readAll().trimmed().toInt(&ok);
    if (!ok) return false;
    raw = v;
    return true;
}

void BatteryMonitor::poll() {
    int raw = 0;
    if (!readRaw(raw)) {
        if (m_valid) { m_valid = false; emit changed(); }
        return;
    }

    const double vadc = raw * m_scaleMv / 1000.0;        // volts at the ADC pin
    const double vbat = vadc * m_ratio * m_cal;          // restored pack voltage

    // Light EMA so the displayed value doesn't twitch on ADC noise.
    m_ema = m_haveEma ? (m_ema * 0.7 + vbat * 0.3) : vbat;
    m_haveEma = true;
    m_voltage = m_ema;
    m_percent = socFromCell(m_voltage / m_cells);
    m_valid = true;
    emit changed();

    const bool lowNow = m_percent <= m_warnPct;
    if (lowNow && !m_wasLow) {
        emit lowBattery(QStringLiteral("电池电量低: %1% (%2V)")
                            .arg(m_percent).arg(m_voltage, 0, 'f', 1),
                        QStringLiteral("warn"));
    }
    m_wasLow = lowNow;
}

// Resting Li-ion/LiPo discharge curve (per cell). Linearly interpolated.
int BatteryMonitor::socFromCell(double v) {
    static const struct { double v; int pct; } curve[] = {
        {4.20, 100}, {4.15, 95}, {4.11, 90}, {4.08, 85}, {4.02, 80},
        {3.98, 75},  {3.95, 70}, {3.91, 65}, {3.87, 60}, {3.85, 55},
        {3.84, 50},  {3.82, 45}, {3.80, 40}, {3.79, 35}, {3.77, 30},
        {3.75, 25},  {3.73, 20}, {3.71, 15}, {3.69, 10}, {3.61, 5},
        {3.30, 0},
    };
    const int n = int(sizeof(curve) / sizeof(curve[0]));
    if (v >= curve[0].v)     return 100;
    if (v <= curve[n - 1].v) return 0;
    for (int i = 0; i < n - 1; ++i) {
        if (v <= curve[i].v && v > curve[i + 1].v) {
            const double t = (v - curve[i + 1].v) / (curve[i].v - curve[i + 1].v);
            return int(curve[i + 1].pct + t * (curve[i].pct - curve[i + 1].pct) + 0.5);
        }
    }
    return 0;
}
