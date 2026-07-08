import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import SkyVision 1.0

ApplicationWindow {
    id: root
    visible: true
    visibility: Window.FullScreen
    color: "black"

    width: 1280
    height: 800

    readonly property int videoW: 960
    readonly property int videoH: 600

    // AP/直连模式下下视是主用视图,启动自动切到下视(默认 currentCamera=forward 无视频)
    Component.onCompleted: appCtl.switchCamera()

    property var events: []

    Connections {
        target: appCtl
        function onEvent(text, severity) {
            const ts = Qt.formatDateTime(new Date(), "HH:mm:ss")
            const list = root.events.slice()
            list.unshift({ ts: ts, text: text, severity: severity })
            if (list.length > 30) list.length = 30
            root.events = list
        }
    }

    // Top status bar
    StatusBar {
        id: statusBar
        x: 0; y: 0
        width: parent.width
        height: 44
        z: 5
        onQrClicked: qrModal.open()
        onWifiClicked: wifiModal.open()
    }

    QRModal {
        id: qrModal
        anchors.centerIn: parent
        width: 490
        height: 620
    }

    WiFiModal {
        id: wifiModal
    }

    // Video at left, native 960x600 + NPU detection overlay
    Item {
        id: videoArea
        x: 0; y: 44
        width: root.videoW
        height: root.videoH
        clip: false   // clip:true 会在视频边缘产生抗锯齿绿条纹

        VideoItem {
            id: video
            objectName: "videoItem"
            anchors.fill: parent
        }

        property var palette: ["#00FF7F", "#FF6347", "#FFD700", "#1E90FF",
                               "#FF69B4", "#00FFFF", "#FFA500", "#9370DB",
                               "#7FFF00", "#FF4500"]
        function colorFor(label) {
            var h = 0
            for (var k = 0; k < label.length; k++) h = (h * 31 + label.charCodeAt(k)) & 0xff
            return videoArea.palette[h % videoArea.palette.length]
        }

        // Detection boxes drawn directly into video frame by Python — no QML overlay needed.

        // 视频区点击: 锁定区绘制(加点/长按完成) 或 跟随目标点选
        MouseArea {
            anchors.fill: parent
            visible: appCtl.zoneDrawMode || appCtl.followMode === 1
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            cursorShape: Qt.CrossCursor
            z: 9
            onClicked: (mouse) => {
                if (mouse.button === Qt.RightButton && appCtl.zoneDrawMode) {
                    appCtl.finishZoneDraw()
                } else {
                    appCtl.videoTapped(mouse.x / width, mouse.y / height)
                }
            }
            onPressAndHold: if (appCtl.zoneDrawMode) appCtl.finishZoneDraw()
        }

        Rectangle {
            visible: appCtl.zoneDrawMode || appCtl.followMode !== 0
            anchors.horizontalCenter: parent.horizontalCenter
            y: 8
            width: hintLbl.implicitWidth + 24
            height: 28
            radius: 14
            color: Qt.rgba(0,0,0,0.75)
            border.color: appCtl.followMode === 2 ? "#00E5FF" : "#FFD700"
            z: 10
            Label {
                id: hintLbl
                anchors.centerIn: parent
                text: appCtl.zoneDrawMode ? "✎ 绘制锁定区 · 单击加点 · 长按完成"
                    : appCtl.followMode === 1 ? "◎ 点击目标框开始跟随"
                    : "◎ 跟随中 " + appCtl.followInfo + " · 按任意方向键接管"
                color: appCtl.followMode === 2 ? "#00E5FF" : "#FFD700"
                font.pixelSize: 13
                font.bold: true
            }
        }

        Rectangle {
            visible: appCtl.detectionCount > 0
            anchors.left: parent.left; anchors.top: parent.top
            anchors.margins: 8
            width: detCountLbl.implicitWidth + 16
            height: 24
            radius: 12
            color: Qt.rgba(0, 0, 0, 0.65)
            border.color: appCtl.zoneViolation ? "#FF3333" : "#7CFC00"
            Label {
                id: detCountLbl
                anchors.centerIn: parent
                text: appCtl.zoneViolation ? "⚠ 锁定区目标·已触发诊断" : ("目标 × " + appCtl.detectionCount)
                color: appCtl.zoneViolation ? "#FF3333" : "#7CFC00"
                font.pixelSize: 13
                font.bold: true
            }
        }
    }

    // Right sidebar event panel
    // Right sidebar split: events on top, drone control below
    Column {
        x: root.videoW; y: 44
        width: parent.width - root.videoW
        height: parent.height - 44
        spacing: 6

        EventPanel {
            id: eventPanel
            width: parent.width
            height: parent.height * 0.5 - 3
            eventsModel: root.events
        }


        DronePanel {
            id: dronePanel
            width: parent.width
            height: parent.height * 0.5 - 3
            onCommand: function(name) {
                var verbs = { "起飞": "takeoff", "降落": "land", "返航": "rtl", "航线": "mission",
                              "左转": "yawl", "右转": "yawr",
                              "前进": "fwd", "后退": "back", "左移": "left", "右移": "right",
                              "升高": "up", "降低": "down", "悬停": "hold" }
                if (verbs[name] !== undefined)
                    appCtl.droneCommand(verbs[name])   // 经wfb空口下发, 返航室内映射LAND
            }
        }
    }

    // Bottom-left button bar below video
    ButtonBar {
        id: buttonBar
        x: 0
        y: 44 + root.videoH
        width: root.videoW
        height: parent.height - y
        onSnapshotClicked: appCtl.snapshot()
        onRecordToggled: appCtl.toggleRecording()
        monitorMode: appCtl.monitorMode
        onLinkModeToggled: appCtl.toggleLinkMode()
        onZoneAlertClicked: zoneModal.open()
        onPlaybackClicked: recModal.open()
        onDiagLogClicked: diagModal.open()
        recording: appCtl.recording
    }

    ZoneAlertModal {
        id: zoneModal
        anchors.centerIn: parent
        width: 480
        height: 360
    }

    RecordingsModal {
        id: recModal
        anchors.centerIn: parent
        width: 600
        height: 480
    }

    DiagLogModal {
        id: diagModal
        anchors.centerIn: parent
        width: 660
        height: 500
    }

    // Floating playback indicator + back-to-live button
    Rectangle {
        visible: appCtl.playbackMode
        x: 8
        y: 52
        width: pbLabel.implicitWidth + 22
        height: 32
        radius: 16
        color: Qt.rgba(0, 0, 0, 0.7)
        border.color: "#FFD700"
        Label {
            id: pbLabel
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 10
            text: "🎬 " + appCtl.playbackFile
            color: "#FFD700"
            font.pixelSize: 12
            font.bold: true
        }
    }
    Button {
        visible: appCtl.playbackMode
        x: root.videoW - width - 8
        y: 52
        width: 110; height: 32
        text: "↩ 返回直播"
        onClicked: appCtl.resumeLive()
        background: Rectangle {
            radius: 16
            color: parent.hovered ? "#3a8" : "#286"
            border.color: "#5cd"
        }
        contentItem: Label {
            text: parent.text; color: "white"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 12; font.bold: true
        }
    }
}
