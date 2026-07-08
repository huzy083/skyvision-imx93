import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: wifiDialog
    modal: true
    width: 720
    height: 720
    anchors.centerIn: parent
    title: "Wi-Fi 网络"

    background: Rectangle {
        color: "#1a1a1a"
        border.color: "#444"
        border.width: 1
        radius: 6
    }

    header: Rectangle {
        color: "#262626"
        height: 44
        Label {
            anchors.fill: parent
            anchors.leftMargin: 16
            verticalAlignment: Text.AlignVCenter
            text: "Wi-Fi 网络  ·  当前: " + (wifiMgr.currentSSID || "—") + "  (" + wifiMgr.wpaState + ")"
            color: "white"
            font.pixelSize: 14
        }
    }

    contentItem: ColumnLayout {
        spacing: 6

        // top bar: refresh + count
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Button {
                text: wifiMgr.busy ? "扫描中..." : "🔄 刷新"
                enabled: !wifiMgr.busy
                onClicked: wifiMgr.scan()
            }
            Item { Layout.fillWidth: true }
            Label {
                text: "共 " + wifiMgr.networks.length + " 个"
                color: "#aaa"
            }
        }

        // SSID list — shrinks when connect-pane visible
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: connectPane.visible ? 180 : -1
            Layout.fillHeight: !connectPane.visible
            color: "#0d0d0d"
            border.color: "#333"

            ListView {
                id: lv
                anchors.fill: parent
                anchors.margins: 4
                clip: true
                model: wifiMgr.networks
                spacing: 2

                delegate: Rectangle {
                    width: ListView.view.width
                    height: 44
                    property bool isSaved: wifiMgr.savedSSIDs.indexOf(modelData.ssid) >= 0
                    color: ma.containsMouse ? "#2a2a2a" : (modelData.ssid === wifiMgr.currentSSID ? "#0a3a0a" : "transparent")
                    border.color: modelData.ssid === wifiMgr.currentSSID ? "#7CFC00" : "transparent"

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        Label {
                            text: modelData.ssid + (modelData.secured ? "  [加密]" : "") + (isSaved ? "  ✓已保存" : "")
                            color: isSaved ? "#7CFC00" : "white"
                            font.pixelSize: 14
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Label {
                            text: modelData.signal + " dBm  " + modelData.freq + "MHz"
                            color: "#aaa"
                            font.pixelSize: 12
                        }
                    }

                    MouseArea {
                        id: ma
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (parent.isSaved) {
                                // saved network: reuse stored psk, connect directly
                                wifiMgr.connectTo(modelData.ssid, "")
                                connectPane.visible = false
                            } else {
                                connectPane.ssid = modelData.ssid
                                connectPane.secured = modelData.secured
                                connectPane.visible = true
                                pwdInput.text = ""
                            }
                        }
                    }
                }
            }
        }

        // connect pane (compact, fixed height, no keyboard inside)
        Rectangle {
            id: connectPane
            property string ssid: ""
            property bool secured: false
            visible: false
            Layout.fillWidth: true
            Layout.preferredHeight: 130
            color: "#202020"
            border.color: "#444"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 6
                Label {
                    text: "连接到 " + connectPane.ssid
                    color: "white"
                    font.bold: true
                    font.pixelSize: 15
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    TextField {
                        id: pwdInput
                        Layout.fillWidth: true
                        Layout.preferredHeight: 38
                        placeholderText: connectPane.secured ? "密码（用下方键盘）" : "(开放网络)"
                        enabled: connectPane.secured
                        readOnly: true
                        inputMethodHints: Qt.ImhNone
                        echoMode: showPwd.checked ? TextInput.Normal : TextInput.Password
                        color: "white"
                        font.pixelSize: 18
                        background: Rectangle { color: "#0d0d0d"; border.color: "#444" }
                    }
                    CheckBox {
                        id: showPwd
                        text: "明文"
                        contentItem: Label { text: "明文"; color: "white"; leftPadding: 24; verticalAlignment: Text.AlignVCenter }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    Button {
                        text: "取消"
                        Layout.preferredHeight: 36
                        onClicked: connectPane.visible = false
                    }
                    Button {
                        text: wifiMgr.busy ? "连接中..." : "连接"
                        Layout.preferredHeight: 36
                        highlighted: true
                        enabled: !wifiMgr.busy
                        onClicked: {
                            wifiMgr.connectTo(connectPane.ssid, pwdInput.text)
                            connectPane.visible = false
                        }
                    }
                }
            }
        }

        // On-screen keyboard pinned at bottom — only when connect pane is open
        OnScreenKeyboard {
            Layout.fillWidth: true
            Layout.preferredHeight: 240
            visible: connectPane.visible && connectPane.secured
            onKeyPressed: (ch) => pwdInput.text += ch
            onBackspacePressed: pwdInput.text = pwdInput.text.slice(0, -1)
        }
    }

    Component.onCompleted: wifiMgr.scan()
}
