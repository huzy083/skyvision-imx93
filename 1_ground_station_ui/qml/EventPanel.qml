import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    color: Qt.rgba(0, 0, 0, 0.55)
    border.color: Qt.rgba(1, 1, 1, 0.1)
    border.width: 1
    radius: 6

    property var eventsModel: []

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: "Qwen 诊断"
                color: "white"
                font.pixelSize: 18
                font.bold: true
                Layout.fillWidth: true
            }
            Label {
                text: panel.eventsModel.length
                color: "#AAAAAA"
                font.pixelSize: 14
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Qt.rgba(1, 1, 1, 0.15) }

        ListView {
            id: lv
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            model: panel.eventsModel
            spacing: 2
            delegate: Rectangle {
                width: ListView.view.width
                height: row.implicitHeight + 12
                radius: 3
                color: index % 2 === 0 ? Qt.rgba(1, 1, 1, 0.03) : "transparent"

                RowLayout {
                    id: row
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    anchors.topMargin: 4
                    anchors.bottomMargin: 4
                    spacing: 8

                    Rectangle {
                        implicitWidth: 8; implicitHeight: 8; radius: 4
                        color: modelData.severity === "alert" ? "#FF6347"
                             : modelData.severity === "warn"  ? "#FFD700"
                             : "#7CFC00"
                    }
                    Label {
                        text: modelData.ts
                        color: "#AAAAAA"
                        font.family: "monospace"
                        font.pixelSize: 14
                    }
                    Label {
                        text: modelData.text
                        color: "white"
                        font.pixelSize: 17
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                visible: panel.eventsModel.length === 0
                text: "暂无诊断结果"
                color: "#666666"
                font.pixelSize: 16
            }
        }
    }
}
