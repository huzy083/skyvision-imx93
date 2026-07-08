import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: kb
    color: "#262626"
    border.color: "#444"
    radius: 4
    implicitHeight: 240

    signal keyPressed(string ch)
    signal backspacePressed()

    property bool shift: false
    property int mode: 0  // 0=letters, 1=symbols

    readonly property var lettersLc: [
        "qwertyuiop",
        "asdfghjkl",
        "zxcvbnm",
    ]
    readonly property var lettersUc: [
        "QWERTYUIOP",
        "ASDFGHJKL",
        "ZXCVBNM",
    ]
    readonly property var symbols: [
        "1234567890",
        "!@#$%&*()-",
        "_+=.,;:'\"",
    ]
    readonly property var symbols2: [
        "<>[]{}/\\|",
        "~`?^",
        "",
    ]

    function rowChars(idx) {
        if (mode === 1) return symbols[idx]
        return (shift ? lettersUc : lettersLc)[idx]
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 4

        Repeater {
            model: 3
            RowLayout {
                property int rowIdx: index
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 3
                Repeater {
                    model: kb.rowChars(rowIdx).length
                    Button {
                        property string ch: kb.rowChars(rowIdx).charAt(index)
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        text: ch
                        font.pixelSize: 16
                        background: Rectangle {
                            color: parent.down ? "#5a5" : "#3a3a3a"
                            border.color: "#555"
                            radius: 3
                        }
                        contentItem: Label {
                            text: parent.text
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.pixelSize: 16
                        }
                        onClicked: kb.keyPressed(ch)
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 3

            Button {
                Layout.preferredWidth: 70
                Layout.fillHeight: true
                text: kb.shift ? "⇪" : "⇧"
                background: Rectangle {
                    color: kb.shift ? "#7CFC00" : "#3a3a3a"
                    border.color: "#555"
                    radius: 3
                }
                contentItem: Label {
                    text: parent.text
                    color: kb.shift ? "black" : "white"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 16
                    font.bold: true
                }
                onClicked: kb.shift = !kb.shift
            }

            Button {
                Layout.preferredWidth: 70
                Layout.fillHeight: true
                text: kb.mode === 1 ? "ABC" : "123"
                background: Rectangle {
                    color: "#3a3a3a"
                    border.color: "#555"
                    radius: 3
                }
                contentItem: Label {
                    text: parent.text
                    color: "white"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 14
                    font.bold: true
                }
                onClicked: kb.mode = (kb.mode + 1) % 2
            }

            Button {
                Layout.fillWidth: true
                Layout.fillHeight: true
                text: "space"
                background: Rectangle {
                    color: parent.down ? "#5a5" : "#3a3a3a"
                    border.color: "#555"
                    radius: 3
                }
                contentItem: Label {
                    text: parent.text
                    color: "#aaa"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 14
                }
                onClicked: kb.keyPressed(" ")
            }

            Button {
                Layout.preferredWidth: 80
                Layout.fillHeight: true
                text: "⌫"
                background: Rectangle {
                    color: parent.down ? "#a55" : "#3a3a3a"
                    border.color: "#555"
                    radius: 3
                }
                contentItem: Label {
                    text: parent.text
                    color: "white"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 18
                    font.bold: true
                }
                onClicked: kb.backspacePressed()
            }
        }
    }
}
