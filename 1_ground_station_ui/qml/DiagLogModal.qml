import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// 诊断记录查看器: 读 skyvision-diag 落盘的 diagnosis.jsonl
// 普通条目=Qwen诊断结论; zone_alert条目=锁定区告警(可点开归档截图)
Popup {
    id: dlg
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    padding: 0

    onOpened: { preview.source = ""; appCtl.refreshDiagLog() }

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
                text: "诊断记录 (" + (appCtl.diagLog ? appCtl.diagLog.length : 0) + " 条)"
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

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: appCtl.diagLog
            delegate: Rectangle {
                width: ListView.view.width
                height: 60
                color: index % 2 ? "#1e1e28" : "transparent"
                property bool isAlert: modelData.type === "zone_alert"

                Column {
                    anchors.left: parent.left
                    anchors.right: viewBtn.visible ? viewBtn.left : parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 14
                    anchors.rightMargin: 10
                    spacing: 2
                    Label {
                        width: parent.width
                        text: isAlert
                              ? "◎ 锁定区告警 · " + (modelData.labels ? modelData.labels.join(", ") : "")
                              : (modelData.zone ? "◎ " : "") + (modelData.part || "?") + "   "
                                + (modelData.is_defect ? "✘ " + (modelData.defect_type || "缺陷")
                                                       : "✔ 正常")
                        color: isAlert ? "#FFD700"
                             : modelData.is_defect ? "#FF6B6B" : "#7CFC00"
                        font.pixelSize: 13
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    Label {
                        width: parent.width
                        text: (modelData.iso || "")
                              + (isAlert ? "" : ("   " + (modelData.reason || "")))
                        color: "#9aa"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                }
                Button {
                    id: viewBtn
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.rightMargin: 12
                    visible: isAlert && !!modelData.snapshot
                    text: "查看截图"
                    onClicked: preview.source = "file://" + modelData.snapshot
                }
            }
            Label {
                anchors.centerIn: parent
                visible: !appCtl.diagLog || appCtl.diagLog.length === 0
                text: "暂无诊断记录"
                color: "#778"
                font.pixelSize: 14
            }
        }
    }

    // 归档截图全屏预览(挂 Overlay 全屏; 作为 Popup 子项会被塞进 contentItem
    // 的 ColumnLayout, anchors 在布局内是未定义行为), 点任意处关闭
    Rectangle {
        parent: Overlay.overlay
        anchors.fill: parent
        visible: preview.source.toString() !== ""
        color: "black"
        z: 99
        Image {
            id: preview
            anchors.fill: parent
            anchors.margins: 4
            fillMode: Image.PreserveAspectFit
            asynchronous: true
        }
        Label {
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottomMargin: 8
            text: "点击关闭"
            color: "#aaa"
            font.pixelSize: 12
        }
        MouseArea {
            anchors.fill: parent
            onClicked: preview.source = ""
        }
    }
}
