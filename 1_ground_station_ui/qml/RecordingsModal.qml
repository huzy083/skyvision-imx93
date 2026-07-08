import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: dlg
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    padding: 0

    property string kindFilter: "all"
    readonly property var filtered:
        (appCtl.recordings || []).filter(function (f) {
            return dlg.kindFilter === "all" || f.kind === dlg.kindFilter
        })

    onOpened: { imgPreview.source = ""; appCtl.refreshRecordings() }

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
                text: "回放 (" + dlg.filtered.length + "/" + (appCtl.recordings ? appCtl.recordings.length : 0) + ")"
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
                onClicked: dlg.close()
                contentItem: Label { text: parent.text; color: "white"; font.pixelSize: 18 }
                background: Rectangle { color: "transparent" }
                width: 30; height: 30
            }
        }

        // 分类过滤: 全部 / 视频(相机录像) / 录屏 / 截图
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 8
            spacing: 6
            Repeater {
                model: [["all", "全部"], ["video", "视频"], ["screen", "录屏"], ["image", "截图"]]
                Button {
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData[1]
                    checkable: true
                    checked: dlg.kindFilter === modelData[0]
                    onClicked: dlg.kindFilter = modelData[0]
                    contentItem: Label {
                        text: parent.text
                        color: parent.checked ? "white" : "#9ab"
                        font.pixelSize: 13
                        font.bold: parent.checked
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: 4
                        color: parent.checked ? "#3a6ea5" : Qt.rgba(1, 1, 1, 0.06)
                        border.color: parent.checked ? "#5a8ec5" : Qt.rgba(1, 1, 1, 0.15)
                    }
                }
            }
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: dlg.filtered
            delegate: Rectangle {
                id: row
                width: ListView.view.width
                height: 56
                property bool confirmDelete: false
                color: confirmDelete ? "#3a2028"
                     : (rowMa.containsMouse ? "#2c2c38" : "transparent")

                // beneath the buttons: long-press arms delete, tap elsewhere cancels
                MouseArea {
                    id: rowMa
                    anchors.fill: parent
                    hoverEnabled: true
                    onPressAndHold: row.confirmDelete = true
                    onClicked: row.confirmDelete = false
                }
                // auto-disarm after 4s of no decision
                Timer {
                    running: row.confirmDelete
                    interval: 4000
                    onTriggered: row.confirmDelete = false
                }

                Column {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 14
                    Label {
                        text: modelData.name
                        color: row.confirmDelete ? "#ff9a9a" : "white"
                        font.pixelSize: 13
                    }
                    Label {
                        text: row.confirmDelete
                              ? "长按删除 · 确认?"
                              : (modelData.mtime + "   " + modelData.size_mb + " MB")
                        color: row.confirmDelete ? "#ff9a9a" : "#9aa"
                        font.pixelSize: 11
                    }
                }
                Button {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.rightMargin: 12
                    visible: !row.confirmDelete
                    property bool isImage: modelData.name.endsWith(".jpg")
                    text: isImage ? "◉ 查看" : "▶ 播放"
                    onClicked: {
                        if (isImage) {
                            imgPreview.source = "file://" + modelData.path
                        } else {
                            appCtl.playRecording(modelData.path)
                            dlg.close()
                        }
                    }
                }
                Row {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.rightMargin: 12
                    spacing: 8
                    visible: row.confirmDelete
                    Button {
                        text: "✕ 删除"
                        onClicked: {
                            appCtl.deleteRecording(modelData.path)
                            row.confirmDelete = false
                        }
                        contentItem: Label {
                            text: parent.text; color: "white"
                            font.pixelSize: 13; font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                        }
                        background: Rectangle { color: "#c0392b"; radius: 4 }
                    }
                    Button {
                        text: "取消"
                        onClicked: row.confirmDelete = false
                    }
                }
            }
            Label {
                anchors.centerIn: parent
                visible: dlg.filtered.length === 0
                text: "该分类下暂无文件"
                color: "#778"
                font.pixelSize: 14
            }
        }
    }

    // 截图全屏预览(挂 Overlay 全屏, 不能作为 Popup 子项——会被塞进
    // contentItem 的 ColumnLayout, anchors 在布局内是未定义行为), 点任意处关闭
    Rectangle {
        parent: Overlay.overlay
        anchors.fill: parent
        visible: imgPreview.source.toString() !== ""
        color: "black"
        z: 99
        Image {
            id: imgPreview
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
            onClicked: imgPreview.source = ""
        }
    }
}
