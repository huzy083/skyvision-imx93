#pragma once
#include <QObject>
#include <QString>
#include <QTimer>

// Polls the i.MX93 ADC (Linux IIO sysfs) fed by an on-board resistor divider
// and exposes the battery pack voltage / state-of-charge to QML (as `batt.*`).
//
//   Vbat --[R_TOP]--+( ADC in_voltageN )--[R_BOTTOM]--GND
//   Vbat = raw * scale_mV/1000 * (R_TOP+R_BOTTOM)/R_BOTTOM * cal
//
// SoC is derived from a per-cell Li-ion/LiPo discharge curve so it is correct
// for any pack size (cells configurable). Values are lightly EMA-smoothed.
class BatteryMonitor : public QObject {
    Q_OBJECT
    Q_PROPERTY(double voltage     READ voltage     NOTIFY changed)  // whole pack, volts
    Q_PROPERTY(double cellVoltage READ cellVoltage NOTIFY changed)  // per-cell, volts
    Q_PROPERTY(int    percent     READ percent     NOTIFY changed)  // 0..100
    Q_PROPERTY(bool   valid       READ valid       NOTIFY changed)  // ADC readable
    Q_PROPERTY(bool   low         READ low         NOTIFY changed)  // <= warn threshold
public:
    explicit BatteryMonitor(QObject *parent = nullptr);

    double voltage() const { return m_voltage; }
    double cellVoltage() const { return m_cells > 0 ? m_voltage / m_cells : 0.0; }
    int    percent() const { return m_percent; }
    bool   valid() const { return m_valid; }
    bool   low() const { return m_valid && m_percent <= m_warnPct; }

signals:
    void changed();
    // Raised once each time the pack crosses below the warning threshold.
    void lowBattery(const QString &text, const QString &severity);

private slots:
    void poll();

private:
    bool readRaw(int &raw) const;
    void loadScale();                 // read in_voltage_scale (mV/LSB) once
    static int socFromCell(double vcell);  // per-cell volts -> 0..100 %

    QTimer  m_timer;
    QString m_rawPath;
    double  m_scaleMv = 0.0;          // mV per LSB
    double  m_ratio   = 9.2;          // (R_TOP+R_BOTTOM)/R_BOTTOM
    double  m_cal     = 1.0;
    int     m_cells   = 3;
    int     m_warnPct = 20;

    double  m_voltage = 0.0;
    double  m_ema     = 0.0;
    bool    m_haveEma = false;
    int     m_percent = 0;
    bool    m_valid   = false;
    bool    m_wasLow  = false;
};
