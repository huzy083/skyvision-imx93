import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    color: Qt.rgba(0, 0, 0, 0.55)
    border.color: Qt.rgba(1, 1, 1, 0.1)
    border.width: 1
    radius: 6

    signal command(string name)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        Label {
            text: "无人机控制"
            color: "white"
            font.pixelSize: 16
            font.bold: true
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.15) }

        // 飞机状态已移至视频下方 ButtonBar 状态条

        // D-pad: ↑ ← ⏺ → ↓ + altitude
        GridLayout {
            columns: 4
            columnSpacing: 8
            rowSpacing: 8
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 4

            DirButton { glyph: "左转"; cmd: "左转"; tone: "#FFD27F"; onTriggered: panel.command(cmd) }
            DirButton { glyph: "▲"; cmd: "前进"; onTriggered: panel.command(cmd) }
            DirButton { glyph: "右转"; cmd: "右转"; tone: "#FFD27F"; onTriggered: panel.command(cmd) }
            DirButton { glyph: "↑"; cmd: "升高"; onTriggered: panel.command(cmd) }

            DirButton { glyph: "◀"; cmd: "左移"; onTriggered: panel.command(cmd) }
            DirButton { glyph: "悬停"; cmd: "悬停"; tone: "#4488FF"; onTriggered: panel.command(cmd) }
            DirButton { glyph: "▶"; cmd: "右移"; onTriggered: panel.command(cmd) }
            Item { Layout.preferredWidth: 56; Layout.preferredHeight: 56 }

            Button {
                // 目标跟随开关: 点选画面里的检测框, 自动偏航+升降对中
                Layout.preferredWidth: 56
                Layout.preferredHeight: 56
                onClicked: appCtl.toggleFollow()
                background: Rectangle {
                    radius: 4
                    color: appCtl.followMode === 2 ? Qt.rgba(0, 0.7, 0.85, 0.35)
                         : appCtl.followMode === 1 ? Qt.rgba(1, 0.84, 0, 0.25)
                         : parent.down ? Qt.rgba(1, 1, 1, 0.25) : Qt.rgba(1, 1, 1, 0.08)
                    border.color: appCtl.followMode === 2 ? "#00E5FF"
                                : appCtl.followMode === 1 ? "#FFD700" : Qt.rgba(1, 1, 1, 0.2)
                    border.width: appCtl.followMode !== 0 ? 2 : 1
                }
                contentItem: Label {
                    text: appCtl.followMode === 2 ? "跟随中"
                        : appCtl.followMode === 1 ? "点目标" : "跟随"
                    color: appCtl.followMode === 2 ? "#00E5FF"
                         : appCtl.followMode === 1 ? "#FFD700" : "white"
                    font.pixelSize: 14
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            DirButton { glyph: "▼"; cmd: "后退"; onTriggered: panel.command(cmd) }
            Item { Layout.preferredWidth: 56; Layout.preferredHeight: 56 }
            DirButton { glyph: "↓"; cmd: "降低"; onTriggered: panel.command(cmd) }
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            ActionButton {
                Layout.fillWidth: true
                text: "起飞"
                tone: "#33AA33"
                // 软锁: ready=机上uavstate综合判定(双源新鲜+未发散+飞控连+上锁中)
                enabled: appCtl.uavFresh && appCtl.uavState.ready === true
                opacity: enabled ? 1.0 : 0.35
                onClicked: takeoffConfirm.open()
            }
            ActionButton {
                Layout.fillWidth: true
                text: "航线"
                tone: "#4488FF"
                onClicked: missionSelect.open()
            }
            ActionButton {
                Layout.fillWidth: true
                text: "返航"
                tone: "#FFAA00"
                onClicked: panel.command("返航")
            }
            ActionButton {
                Layout.fillWidth: true
                text: "降落"
                tone: "#FF4444"
                onClicked: panel.command("降落")
            }
        }
    }

    Popup {
        id: missionSelect
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        modal: true; dim: true; padding: 20
        background: Rectangle { color: "#1a1a1a"; radius: 10; border.color: "#4488FF"; border.width: 1 }
        contentItem: ColumnLayout {
            spacing: 10
            Label {
                text: "选择巡检航线"
                color: "white"; font.pixelSize: 18; font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }
            Label {
                text: "⚠ 地面选择即自动起飞! 确保螺旋桨区域无人"
                color: "#FF8800"; font.pixelSize: 13; font.bold: true
                Layout.alignment: Qt.AlignHCenter
            }
            Label {
                text: "悬停中选择则直接进入航线 · 任何手动按键立即终止"
                color: "#FFC107"; font.pixelSize: 12
                Layout.alignment: Qt.AlignHCenter
            }
            MissionOption {
                mName: "航线 1 · 弓字扫描 (默认)"
                mDesc: "1.25m 扫至 y-1.05 → 升 1.60m 反向扫回 · 7 航点 · 约 60s"
                mVerb: "mission1"
            }
            MissionOption {
                mName: "航线 2 · 矩形环巡"
                mDesc: "1.40m 高度绕 0.7×0.6m 矩形一圈回原点 · 6 航点 · 约 45s"
                mVerb: "mission2"
            }
            MissionOption {
                mName: "航线 3 · 垂直剖面"
                mDesc: "塔前定点 1.0→1.3→1.6m 分层扫查后退回 · 5 航点 · 约 40s"
                mVerb: "mission3"
            }
            Button {
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: 110; implicitHeight: 38
                background: Rectangle { radius: 8; color: parent.down ? "#333" : "#2a2a2a"; border.color: "#666"; border.width: 1 }
                contentItem: Label { text: "取消"; color: "white"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                onClicked: missionSelect.close()
            }
        }
    }

    component MissionOption: Button {
        property string mName
        property string mDesc
        property string mVerb
        Layout.fillWidth: true
        implicitHeight: 62
        implicitWidth: 400
        onClicked: { missionSelect.close(); appCtl.droneCommand(mVerb) }
        background: Rectangle {
            radius: 8
            color: parent.down ? Qt.rgba(0.27, 0.53, 1, 0.35)
                 : parent.hovered ? Qt.rgba(0.27, 0.53, 1, 0.22) : Qt.rgba(1, 1, 1, 0.06)
            border.color: "#4488FF"; border.width: 1
        }
        contentItem: Column {
            spacing: 3
            leftPadding: 12
            Label { text: parent.parent.mName; color: "white"; font.pixelSize: 15; font.bold: true }
            Label { text: parent.parent.mDesc; color: "#9ab"; font.pixelSize: 12 }
        }
    }

    Popup {
        id: takeoffConfirm
        parent: Overlay.overlay
        anchors.centerIn: Overlay.overlay
        modal: true; dim: true; padding: 24
        background: Rectangle { color: "#1a1a1a"; radius: 10; border.color: "#33AA33"; border.width: 1 }
        contentItem: ColumnLayout {
            spacing: 16
            Label { text: "确认起飞? (1米定高)"; color: "white"; font.pixelSize: 20; font.bold: true; Layout.alignment: Qt.AlignHCenter }
            Label { text: "确保螺旋桨区域无人!"; color: "#FFC107"; font.pixelSize: 14; Layout.alignment: Qt.AlignHCenter }
            RowLayout {
                spacing: 16; Layout.alignment: Qt.AlignHCenter
                Button {
                    implicitWidth: 110; implicitHeight: 42
                    background: Rectangle { radius: 8; color: parent.down ? "#333" : "#2a2a2a"; border.color: "#666"; border.width: 1 }
                    contentItem: Label { text: "取消"; color: "white"; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: takeoffConfirm.close()
                }
                Button {
                    implicitWidth: 110; implicitHeight: 42
                    background: Rectangle { radius: 8; color: parent.down ? "#1F7A1F" : "#33AA33"; border.width: 0 }
                    contentItem: Label { text: "起飞"; color: "white"; font.pixelSize: 15; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: { takeoffConfirm.close(); panel.command("起飞"); }
                }
            }
        }
    }

    component DirButton: Button {
        property string glyph
        property string cmd
        property color tone: "#FFFFFF"
        signal triggered()
        // 按住连发(~4Hz): 机上每次平移一小步, 松手即停(目标点只超前一步, 丢包也不冲)
        autoRepeat: true
        autoRepeatDelay: 300
        autoRepeatInterval: 250
        Layout.preferredWidth: 56
        Layout.preferredHeight: 56
        background: Rectangle {
            radius: 4
            color: parent.down    ? Qt.rgba(1, 1, 1, 0.25)
                 : parent.hovered ? Qt.rgba(1, 1, 1, 0.15)
                 :                  Qt.rgba(1, 1, 1, 0.08)
            border.color: Qt.rgba(1, 1, 1, 0.2)
            border.width: 1
        }
        contentItem: Label {
            text: parent.glyph
            color: parent.tone
            font.pixelSize: parent.glyph.length > 1 ? 15 : 22   // 文字按钮(左转/右转)用小号
            font.bold: parent.glyph.length > 1
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        onClicked: triggered()
    }

    component ActionButton: Button {
        property color tone: "#4488FF"
        Layout.preferredHeight: 42
        background: Rectangle {
            radius: 4
            color: parent.down    ? Qt.darker(parent.tone, 1.2)
                 : parent.hovered ? parent.tone
                 :                  Qt.rgba(parent.tone.r, parent.tone.g, parent.tone.b, 0.55)
            border.color: parent.tone
            border.width: 1
        }
        contentItem: Label {
            text: parent.text
            color: "white"
            font.pixelSize: 14
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
    }
}
