import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: bar
    color: Qt.rgba(0, 0, 0, 0.55)
    border.color: Qt.rgba(1, 1, 1, 0.1)
    border.width: 1

    signal qrClicked()
    signal wifiClicked()

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        spacing: 12

        Label {
            text: "SkyVision · 地面站"
            color: "white"
            font.pixelSize: 18
            font.bold: true
        }

        Rectangle {
            implicitWidth: 1
            Layout.fillHeight: true
            Layout.topMargin: 8
            Layout.bottomMargin: 8
            color: Qt.rgba(1, 1, 1, 0.2)
        }

        StatusItem { label: "状态"; value: appCtl.linkStatus; valueColor: appCtl.fps > 5 ? "#7CFC00" : "#FF6347" }
        StatusItem { label: "FPS"; value: appCtl.fps.toFixed(1) }
        StatusItem { label: "码率"; value: appCtl.bitrateMbps.toFixed(1) + " Mbps" }
        StatusItem { label: "延迟"; value: appCtl.latencyMs.toFixed(0) + " ms" }
        StatusItem {
            label: "电量"
            value: batt.valid ? (batt.percent + "% · " + batt.voltage.toFixed(1) + "V") : "--"
            valueColor: !batt.valid ? "#AAAAAA"
                        : batt.percent > 40 ? "#7CFC00"
                        : batt.percent > 20 ? "#FFC107" : "#FF6347"
        }

        Item { Layout.fillWidth: true }

        Label {
            text: appCtl.cameraName
            color: "#7CFC00"
            font.pixelSize: 14
            font.bold: true
        }

        Button {
            text: "⇆"
            implicitWidth: 44
            implicitHeight: 32
            ToolTip.visible: hovered
            ToolTip.text: "切换前/下视摄像头"
            background: Rectangle {
                radius: 16
                color: parent.down ? Qt.rgba(1,1,1,0.25) : parent.hovered ? Qt.rgba(1,1,1,0.15) : Qt.rgba(1,1,1,0.08)
                border.color: Qt.rgba(1,1,1,0.3)
                border.width: 1
            }
            contentItem: Label {
                text: parent.text
                color: "white"
                font.pixelSize: 20
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: appCtl.switchCamera()
        }

        Button {
            implicitWidth: 44
            implicitHeight: 32
            ToolTip.visible: hovered
            ToolTip.text: "Wi-Fi (" + (wifiMgr.currentSSID || "未连接") + ")"
            background: Rectangle {
                radius: 16
                color: parent.down ? Qt.rgba(255,215,0,0.35) : parent.hovered ? Qt.rgba(255,215,0,0.22) : Qt.rgba(255,215,0,0.10)
                border.color: "#FFD700"
                border.width: 1
            }
            contentItem: Label {
                text: "WiFi"
                color: "white"
                font.pixelSize: 12
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: bar.wifiClicked()
        }

        Button {
            implicitWidth: 44
            implicitHeight: 32
            ToolTip.visible: hovered
            ToolTip.text: "扫码远程访问 (192.168.10.1:8080)"
            background: Rectangle {
                radius: 16
                color: parent.down ? Qt.rgba(124,252,255,0.35) : parent.hovered ? Qt.rgba(124,252,255,0.22) : Qt.rgba(124,252,255,0.10)
                border.color: "#7CFCFF"
                border.width: 1
            }
            contentItem: Label {
                text: "QR"
                color: "white"
                font.pixelSize: 14
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: bar.qrClicked()
        }

        Button {
            implicitWidth: 44
            implicitHeight: 32
            ToolTip.visible: hovered
            ToolTip.text: "关机"
            background: Rectangle {
                radius: 16
                color: parent.down ? Qt.rgba(255,99,71,0.35) : parent.hovered ? Qt.rgba(255,99,71,0.22) : Qt.rgba(255,99,71,0.10)
                border.color: "#FF6347"
                border.width: 1
            }
            contentItem: Label {
                text: "关"
                color: "#FF6347"
                font.pixelSize: 15
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            onClicked: shutdownConfirm.open()
        }

        Label {
            text: appCtl.clockText
            color: "white"
            font.family: "monospace"
            font.pixelSize: 16
            Layout.leftMargin: 6
            Layout.minimumWidth: implicitWidth
        }
    }

    Popup {
        id: shutdownConfirm
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        modal: true
        dim: true
        padding: 24
        background: Rectangle {
            color: "#1a1a1a"
            radius: 10
            border.color: "#FF6347"
            border.width: 1
        }
        contentItem: ColumnLayout {
            spacing: 18
            Label {
                text: "确认关闭地面站？"
                color: "white"
                font.pixelSize: 20
                font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }
            RowLayout {
                spacing: 16
                Layout.alignment: Qt.AlignHCenter
                Button {
                    implicitWidth: 120; implicitHeight: 44
                    background: Rectangle { radius: 8; color: parent.down ? "#333" : "#2a2a2a"; border.color: "#666"; border.width: 1 }
                    contentItem: Label { text: "取消"; color: "white"; font.pixelSize: 16; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: shutdownConfirm.close()
                }
                Button {
                    implicitWidth: 120; implicitHeight: 44
                    background: Rectangle { radius: 8; color: parent.down ? "#B22222" : "#FF6347"; border.width: 0 }
                    contentItem: Label { text: "关机"; color: "white"; font.pixelSize: 16; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: { shutdownConfirm.close(); appCtl.shutdown(); }
                }
            }
        }
    }

    component StatusItem: RowLayout {
        property string label
        property string value
        property color valueColor: "white"
        spacing: 6
        Label { text: parent.label + ":"; color: "#AAAAAA"; font.pixelSize: 14 }
        Label { text: parent.value; color: parent.valueColor; font.pixelSize: 14; font.bold: true }
    }
}
