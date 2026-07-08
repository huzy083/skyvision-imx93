import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: dlg
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    padding: 0

    background: Rectangle {
        color: "#1a1a1f"
        border.color: "#3a3a45"
        radius: 6
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            height: 38
            color: "#2a2a35"
            Label {
                anchors.centerIn: parent
                text: "巡检锁定区"
                color: "white"
                font.pixelSize: 14
                font.bold: true
            }
            Button {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 6
                text: "×"
                flat: true
                width: 30; height: 30
                onClicked: dlg.close()
                contentItem: Label { text: parent.text; color: "white"; font.pixelSize: 18 }
                background: Rectangle { color: "transparent" }
            }
        }

        ColumnLayout {
            Layout.margins: 20
            spacing: 14

            Label {
                text: "锁定区自动诊断"
                color: "white"
                font.pixelSize: 15
                font.bold: true
            }

            Label {
                text: "在视频画面上画多边形定义巡检锁定区，部件进入后立即标红告警，并自动截图归档 + AI 缺陷诊断上报。"
                color: "#aab"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.preferredWidth: 360
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: "#2a2a35" }

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: appCtl.zonePolygon.length > 0
                          ? ("当前: " + appCtl.zonePolygon.length + " 个顶点")
                          : "尚未绘制"
                    color: "#cce"
                    font.pixelSize: 12
                }
                Item { Layout.fillWidth: true }
                Label {
                    text: appCtl.zoneEnabled ? "● 已启用" : "○ 未启用"
                    color: appCtl.zoneEnabled ? "#7CFC00" : "#778"
                    font.pixelSize: 12
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Button {
                    Layout.fillWidth: true
                    text: appCtl.zoneDrawMode ? "退出绘制" : "开始绘制"
                    highlighted: appCtl.zoneDrawMode
                    onClicked: { appCtl.toggleZoneDraw(); dlg.close() }
                }
                Button {
                    Layout.fillWidth: true
                    text: "清除"
                    enabled: appCtl.zonePolygon.length > 0
                    onClicked: appCtl.clearZone()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                CheckBox {
                    text: "启用锁定区"
                    enabled: appCtl.zonePolygon.length >= 3
                    checked: appCtl.zoneEnabled
                    contentItem: Label {
                        text: parent.text
                        color: parent.enabled ? "white" : "#556"
                        leftPadding: parent.indicator.width + 8
                    }
                    onClicked: appCtl.setZoneEnabled(checked)
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "完成"
                    onClicked: dlg.close()
                }
            }
        }
    }
}
