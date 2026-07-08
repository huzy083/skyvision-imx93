import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    color: Qt.rgba(0, 0, 0, 0.55)
    border.color: Qt.rgba(1, 1, 1, 0.1)
    border.width: 1
    radius: 6

    // RSSI color thresholds (dBm): >= -55 green, >= -70 yellow, else red
    function rssiColor(v) {
        if (v >= -55) return "#7CFC00"
        if (v >= -70) return "#FFD700"
        return "#FF6347"
    }
    function retryColor(p) {
        if (p < 5) return "#7CFC00"
        if (p < 20) return "#FFD700"
        return "#FF6347"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 6

        // Header
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Label {
                text: "📡 链路分析"
                color: "white"
                font.pixelSize: 14
                font.bold: true
                Layout.fillWidth: true
            }
            Rectangle {
                width: 8; height: 8; radius: 4
                color: appCtl.linkActive ? "#7CFC00" : "#666"
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.15) }

        // RSSI gauge — single big number, color-coded
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "实时信号 RSSI"
                    color: "#aab"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }
                Label {
                    text: appCtl.linkRssiMin && appCtl.linkRssiMax
                        ? ("范围 " + appCtl.linkRssiMin + "..." + appCtl.linkRssiMax)
                        : ""
                    color: "#778"
                    font.pixelSize: 10
                }
            }
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: appCtl.linkActive ? (appCtl.linkRssiAvg + " dBm") : "—"
                color: appCtl.linkActive ? panel.rssiColor(appCtl.linkRssiAvg) : "#555"
                font.pixelSize: 28
                font.bold: true
            }
        }

        // Retry % — the headline diagnostic
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 2
            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "MAC 层重传率"
                    color: "#aab"
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }
                Label {
                    text: "← IP 层看不见"
                    color: "#556"
                    font.pixelSize: 9
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 4
                Label {
                    text: appCtl.linkActive ? appCtl.linkRetryPct.toFixed(1) + "%" : "—"
                    color: appCtl.linkActive ? panel.retryColor(appCtl.linkRetryPct) : "#555"
                    font.pixelSize: 22
                    font.bold: true
                }
                Rectangle {
                    // mini bar
                    Layout.fillWidth: true
                    height: 8
                    color: Qt.rgba(1,1,1,0.08)
                    radius: 4
                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: Math.min(parent.width, parent.width * (appCtl.linkRetryPct / 50.0))
                        radius: 4
                        color: panel.retryColor(appCtl.linkRetryPct)
                    }
                }
            }
        }

        // bottom row: pps + kbps + top MCS
        GridLayout {
            Layout.fillWidth: true
            columns: 3
            rowSpacing: 2
            columnSpacing: 8

            Label { text: "帧/秒"; color: "#aab"; font.pixelSize: 10 }
            Label { text: "空中码率"; color: "#aab"; font.pixelSize: 10 }
            Label { text: "主用 MCS"; color: "#aab"; font.pixelSize: 10 }

            Label {
                text: appCtl.linkPps
                color: "white"; font.pixelSize: 16; font.bold: true
            }
            Label {
                text: (appCtl.linkKbps / 1000.0).toFixed(2) + " Mbps"
                color: "white"; font.pixelSize: 16; font.bold: true
            }
            Label {
                text: appCtl.linkMcsTop >= 0 ? appCtl.linkMcsTop : "—"
                color: "white"; font.pixelSize: 16; font.bold: true
            }
        }

        Item { Layout.fillHeight: true } // spacer
    }
}
