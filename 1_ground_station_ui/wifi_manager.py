"""WiFiManager: subprocess wpa_cli wrapper exposed to QML.
Inject into skyvision_ui.py at module load time.
"""
import subprocess
import time
import re
from PySide6.QtCore import QObject, Property, Signal, Slot, QTimer

WIFI_IFACE = "mlan0"
WPA_CLI = "/usr/sbin/wpa_cli"


def _wpa(args, timeout=4):
    """Run wpa_cli -i mlan0 <args>, return stdout string."""
    cmd = [WPA_CLI, "-i", WIFI_IFACE] + (args if isinstance(args, list) else args.split())
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:
        return f"ERR: {e}"


class WiFiManager(QObject):
    networksChanged = Signal()
    statusChanged = Signal()
    busyChanged = Signal()
    savedChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._networks = []
        self._saved_ssids = []
        self._current_ssid = ""
        self._wpa_state = ""
        self._busy = False
        self._refresh_saved()
        self._refresh_status()
        # poll status every 3s
        self._t = QTimer(self)
        self._t.timeout.connect(self._refresh_status)
        self._t.start(3000)

    # ---- properties ----
    @Property("QVariantList", notify=networksChanged)
    def networks(self):
        return self._networks

    @Property("QVariantList", notify=savedChanged)
    def savedSSIDs(self):
        return self._saved_ssids

    @Property(str, notify=statusChanged)
    def currentSSID(self):
        return self._current_ssid

    @Property(str, notify=statusChanged)
    def wpaState(self):
        return self._wpa_state

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    def _set_busy(self, v):
        if v != self._busy:
            self._busy = v
            self.busyChanged.emit()

    # ---- internals ----
    def _refresh_saved(self):
        out = _wpa("list_networks")
        ss = []
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1]:
                ss.append(parts[1])
        if ss != self._saved_ssids:
            self._saved_ssids = ss
            self.savedChanged.emit()

    def _refresh_status(self):
        out = _wpa("status")
        ssid = ""
        state = ""
        for line in out.splitlines():
            if line.startswith("ssid="):
                ssid = line.split("=", 1)[1]
            elif line.startswith("wpa_state="):
                state = line.split("=", 1)[1]
        if ssid != self._current_ssid or state != self._wpa_state:
            self._current_ssid = ssid
            self._wpa_state = state
            self.statusChanged.emit()

    # ---- slots invoked from QML ----
    @Slot()
    def scan(self):
        self._set_busy(True)
        _wpa("scan")
        QTimer.singleShot(2500, self._collect_scan)

    def _collect_scan(self):
        out = _wpa("scan_results")
        nets = []
        seen = set()
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            bssid, freq, sig, flags, ssid = parts[0], parts[1], parts[2], parts[3], parts[4]
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            secured = "PSK" in flags or "WEP" in flags or "EAP" in flags
            try:
                sig_int = int(sig)
            except ValueError:
                sig_int = -100
            nets.append({
                "ssid": ssid,
                "bssid": bssid,
                "freq": freq,
                "signal": sig_int,
                "secured": secured,
            })
        nets.sort(key=lambda n: -n["signal"])
        self._networks = nets
        self.networksChanged.emit()
        self._set_busy(False)

    @Slot(str, str)
    def connectTo(self, ssid, password):
        self._set_busy(True)
        # check if network already exists
        out = _wpa("list_networks")
        net_id = None
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == ssid:
                net_id = parts[0]
                break
        if net_id is None:
            r = _wpa("add_network").strip()
            if not r.isdigit():
                self._set_busy(False)
                return
            net_id = r
            _wpa(["set_network", net_id, "ssid", f'"{ssid}"'])
            if password:
                _wpa(["set_network", net_id, "psk", f'"{password}"'])
            else:
                _wpa(["set_network", net_id, "key_mgmt", "NONE"])
        else:
            if password:
                _wpa(["set_network", net_id, "psk", f'"{password}"'])
        _wpa(["enable_network", net_id])
        _wpa(["select_network", net_id])
        _wpa("save_config")
        QTimer.singleShot(500, self._refresh_saved)
        # trigger DHCP after association
        QTimer.singleShot(4000, self._post_connect)

    def _post_connect(self):
        subprocess.Popen(["/sbin/udhcpc", "-i", WIFI_IFACE, "-q", "-n", "-t", "5"])
        QTimer.singleShot(2000, self._refresh_status)
        QTimer.singleShot(2500, lambda: self._set_busy(False))

    @Slot(str)
    def disconnect_(self, ssid):
        # disable + select removed
        out = _wpa("list_networks")
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 2 and parts[1] == ssid:
                _wpa(["disable_network", parts[0]])
                break
        _wpa("disconnect")
        self._refresh_status()
