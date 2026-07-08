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
        radius: 8
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            height: 38
            color: "#2a2a35"
            Label {
                anchors.centerIn: parent
                text: "扫码访问 SkyVision 远程监控"
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

        Image {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 10
            Layout.bottomMargin: 10
            source: "icons/webui_qr.png"
            fillMode: Image.PreserveAspectFit
            sourceSize.width: 430
            width: 430
            height: 520
        }
    }
}
