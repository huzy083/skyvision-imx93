import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: bar
    color: Qt.rgba(0, 0, 0, 0.55)
    border.color: Qt.rgba(1, 1, 1, 0.1)
    border.width: 1

    property bool recording: false

    signal snapshotClicked()
    signal recordToggled()
    signal zoneAlertClicked()
    signal playbackClicked()
    signal diagLogClicked()
    signal linkModeToggled()
    property bool monitorMode: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        // ---- 无人机状态条: 就绪/电池/飞控/双源位姿 一行横排 ----
        RowLayout {
            id: uavStrip
            Layout.fillWidth: true
            spacing: 10
            property real bv: appCtl.uavState.batt_v !== undefined && appCtl.uavState.batt_v !== null
                              ? appCtl.uavState.batt_v : -1

            Label {
                text: !appCtl.uavFresh ? "● 无人机: 无数据"
                    : appCtl.uavState.diverged ? "⚠ 定位发散"
                    : appCtl.uavState.armed ? "✈ 飞行中"
                    : appCtl.uavState.ready === true ? "✔ 可起飞" : "✘ 未就绪"
                color: !appCtl.uavFresh ? "#888888"
                     : appCtl.uavState.diverged ? "#FF5555"
                     : appCtl.uavState.armed ? "#9FDFFF"
                     : appCtl.uavState.ready === true ? "#7CFC00" : "#FF8800"
                font.pixelSize: 17
                font.bold: true
            }
            Label {
                // 6S: >22.8V(3.8/芯)正常 / >21.6V(3.6/芯)偏低 / 以下告警
                // 注意别用emoji(🔋等SMP字符板子字体没有,渲染成方块)
                text: "电池 " + (uavStrip.bv > 0 ? uavStrip.bv.toFixed(1) + " V" : "-- V")
                color: uavStrip.bv <= 0 ? "#888888"
                     : uavStrip.bv > 22.8 ? "#7CFC00"
                     : uavStrip.bv > 21.6 ? "#FFC107" : "#FF5555"
                font.pixelSize: 17
                font.bold: uavStrip.bv > 0 && uavStrip.bv <= 21.6
            }
            Label {
                visible: appCtl.uavFresh
                // 已连时省掉"飞控已连"前缀, 状态条宽度有限(超宽会把按钮挤出栏外)
                text: (appCtl.uavState.fcu ? "" : "飞控未连 · ")
                    + (appCtl.uavState.mode || "?")
                    + (appCtl.uavState.armed ? "·解锁" : "·上锁")
                color: appCtl.uavState.fcu ? "white" : "#FFC107"
                font.pixelSize: 16
            }
            Label {
                visible: appCtl.uavFresh
                property var l: appCtl.uavState.lio || ({})
                text: "LIO " + (l.x !== null && l.x !== undefined ? l.x.toFixed(2) : "--")
                    + " " + (l.y !== null && l.y !== undefined ? l.y.toFixed(2) : "--")
                    + " " + (l.z !== null && l.z !== undefined ? l.z.toFixed(2) : "--")
                color: appCtl.uavState.lio_fresh ? "#9FDFFF" : "#777777"
                font.family: "monospace"; font.pixelSize: 15
            }
            Label {
                visible: appCtl.uavFresh
                property var e: appCtl.uavState.ekf || ({})
                text: "EKF " + (e.x !== null && e.x !== undefined ? e.x.toFixed(2) : "--")
                    + " " + (e.y !== null && e.y !== undefined ? e.y.toFixed(2) : "--")
                    + " " + (e.z !== null && e.z !== undefined ? e.z.toFixed(2) : "--")
                color: appCtl.uavState.ekf_fresh ? "#B8FFB8" : "#777777"
                font.family: "monospace"; font.pixelSize: 15
            }
            Item { Layout.fillWidth: true }
            Button {
                // 整屏录制(演示视频), MJPEG avi 存 recordings, 回放列表可看
                Layout.preferredHeight: 32
                Layout.preferredWidth: 92
                onClicked: appCtl.toggleScreenRecording()
                contentItem: Label {
                    text: appCtl.screenRecording ? "■ 录屏中" : "● 录屏"
                    color: appCtl.screenRecording ? "#FF5555" : "#9FDFFF"
                    font.pixelSize: 15
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 4
                    color: appCtl.screenRecording ? Qt.rgba(1, 0.2, 0.2, 0.18)
                         : parent.pressed ? Qt.rgba(1, 1, 1, 0.25) : Qt.rgba(1, 1, 1, 0.08)
                    border.color: appCtl.screenRecording ? "#FF5555" : Qt.rgba(1, 1, 1, 0.25)
                }
            }
            Button {
                // 重启机上全套定位栈(FCU+FAST-LIO链+uavstate), 位姿不对时按这个
                // 飞行中禁用; 恢复期间状态条变灰, 转绿(~40s)即完成
                enabled: !(appCtl.uavFresh && appCtl.uavState.armed === true)
                Layout.preferredHeight: 32
                Layout.preferredWidth: 82
                onClicked: appCtl.droneCommand("lreset")
                contentItem: Label {
                    text: "↻ 定位"
                    color: parent.enabled ? "#9FDFFF" : "#556"
                    font.pixelSize: 15
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    radius: 4
                    color: parent.pressed ? Qt.rgba(1, 1, 1, 0.25) : Qt.rgba(1, 1, 1, 0.08)
                    border.color: Qt.rgba(1, 1, 1, 0.25)
                }
            }
        }

        RowLayout {
        Layout.fillWidth: true
        spacing: 8

        ActionButton {
            Layout.fillWidth: true
            text: "◉ 截图"
            onClicked: bar.snapshotClicked()
        }
        ActionButton {
            Layout.fillWidth: true
            text: bar.recording ? "■ 停止" : "● 录像"
            highlighted: bar.recording
            highlightColor: "#FF4444"
            onClicked: bar.recordToggled()
        }
        ActionButton {
            Layout.fillWidth: true
            text: "◎ 锁定区"
            onClicked: bar.zoneAlertClicked()
        }
        ActionButton {
            Layout.fillWidth: true
            text: "▶ 回放"
            onClicked: bar.playbackClicked()
        }
        ActionButton {
            Layout.fillWidth: true
            text: "▤ 诊断记录"
            onClicked: bar.diagLogClicked()
        }
        ActionButton {
            Layout.fillWidth: true
            text: bar.monitorMode ? "远距模式" : "WiFi模式"
            highlighted: bar.monitorMode
            highlightColor: "#FF9500"
            onClicked: bar.linkModeToggled()
        }
        }
    }

    component ActionButton: Button {
        property color highlightColor: "#4488FF"
        Layout.preferredHeight: 50
        // 允许被 RowLayout 压缩(否则按钮多时总宽超过视频区, 溢出盖到右栏)
        Layout.minimumWidth: 48
        leftPadding: 6
        rightPadding: 6
        background: Rectangle {
            radius: 4
            color: parent.highlighted ? parent.highlightColor
                 : parent.hovered    ? Qt.rgba(1, 1, 1, 0.15)
                 :                     Qt.rgba(1, 1, 1, 0.08)
            border.color: Qt.rgba(1, 1, 1, 0.2)
            border.width: 1
        }
        contentItem: Label {
            text: parent.text
            color: "white"
            font.pixelSize: 15
            font.bold: true
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }
}
