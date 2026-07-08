#!/usr/bin/env bash
# Cross-compile the SkyVision C++ UI for the i.MX93 board (aarch64) on the dev box.
#
# WHY cross-compile: the board runs Qt6 6.8.3 (runtime + headers) but ships NO
# build tools — no moc, no Qt6*Tools cmake. So we build on the dev machine with
# aarch64-linux-gnu-g++, a Qt6 *host moc* (from Debian), and a sysroot copied
# from the board. Verified working 2026-06-26: produces a 960x600@15fps native
# UI, zero Python per frame.
#
# Prereqs on the dev box (Ubuntu 24.04):  sudo apt install g++-aarch64-linux-gnu cmake pkg-config
set -euo pipefail

BOARD=${BOARD:-192.168.3.48}
WORK=${WORK:-/tmp/xbuild}
SRC="$(cd "$(dirname "$0")" && pwd)"
SYSROOT="$WORK/sysroot"
HOSTQT="$WORK/hostqt"
mkdir -p "$WORK" "$SYSROOT" "$HOSTQT"

echo "==> 1. Host Qt6 moc (x86) — Debian trixie qt6 6.8.2 dev + dev-tools"
cd "$WORK"; mkdir -p debs
B=https://deb.debian.org/debian/pool/main/q/qt6-base
D=https://deb.debian.org/debian/pool/main/q/qt6-declarative
for u in \
  "$B/qt6-base-dev-tools_6.8.2+dfsg-9+deb13u2_amd64.deb" \
  "$B/qt6-base-dev_6.8.2+dfsg-9+deb13u2_amd64.deb" \
  "$D/qt6-declarative-dev_6.8.2+dfsg-7_amd64.deb"; do
  f=debs/$(basename "$u"); [ -f "$f" ] || curl -sSL -o "$f" "$u"
  dpkg-deb -x "$f" "$HOSTQT"
done
# version files say 6.8.2; board is 6.8.3 (moc output is compatible) -> bump the gate
find "$HOSTQT"/usr/lib/x86_64-linux-gnu/cmake/Qt6*Tools -name '*.cmake' \
  -exec sed -i 's/6\.8\.2/6.8.3/g' {} +
# stub tool binaries referenced-but-absent (qmake6) so imported-target checks pass
grep -rhoE '\$\{_IMPORT_PREFIX\}/[A-Za-z0-9/_.+-]+' \
  "$HOSTQT"/usr/lib/x86_64-linux-gnu/cmake/Qt6*Tools/*.cmake | sed "s#\${_IMPORT_PREFIX}#$HOSTQT/usr#" | sort -u | \
  while read -r p; do [ -e "$p" ] || { mkdir -p "$(dirname "$p")"; printf '#!/bin/sh\nexit 0\n' >"$p"; chmod +x "$p"; }; done

echo "==> 2. gstreamer 1.x dev headers + .pc ON THE BOARD (ABI-stable across 1.x)"
# Headers come from any 1.24+ gst sysroot; here we assume they are already installed
# on the board (see docs/PYTHON_TO_CPP_MIGRATION.md §7). Re-run that one-time step
# if /usr/include/gstreamer-1.0 is missing on the board.

echo "==> 3. Target sysroot from the board (Qt6 + gst + glib + qml plugins + .a)"
ssh root@"$BOARD" "tar cf - -C / \
  --exclude='usr/lib/python3.13' --exclude='usr/lib/modules' --exclude='usr/lib/go' \
  --exclude='usr/lib/udev' --exclude='usr/lib/firmware' --exclude='usr/lib/dri' \
  usr/include usr/lib 2>/dev/null" | tar xf - -C "$SYSROOT"

echo "==> 4. Configure + build"
cmake -S "$SRC" -B "$WORK/build" \
  -DCMAKE_TOOLCHAIN_FILE="$SRC/aarch64-board.cmake" \
  -DCMAKE_BUILD_TYPE=Release \
  -DWITH_TFLITE=${WITH_TFLITE:-OFF} -DWITH_MOSQUITTO=${WITH_MOSQUITTO:-OFF} \
  -DQT_HOST_PATH="$HOSTQT/usr" \
  -DQT_HOST_PATH_CMAKE_DIR="$HOSTQT/usr/lib/x86_64-linux-gnu/cmake"
cmake --build "$WORK/build" -j"$(nproc)"

echo "==> Done: $WORK/build/skyvision_ui"
echo "    Deploy:  scp $WORK/build/skyvision_ui root@$BOARD:/root/ui-qml/skyvision_ui_cpp"
