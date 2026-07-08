set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(SYSROOT /tmp/xbuild/sysroot)
set(CMAKE_SYSROOT ${SYSROOT})
set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)

set(CMAKE_FIND_ROOT_PATH ${SYSROOT})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# let the linker resolve transitive NEEDED libs (icu, png, wayland, ...) from the board sysroot
set(CMAKE_EXE_LINKER_FLAGS_INIT "-Wl,-rpath-link,${SYSROOT}/usr/lib")

# pkg-config resolves gstreamer/glib from the sysroot, with sysroot-prefixed paths
set(ENV{PKG_CONFIG_LIBDIR} "${SYSROOT}/usr/lib/pkgconfig:${SYSROOT}/usr/share/pkgconfig")
set(ENV{PKG_CONFIG_SYSROOT_DIR} "${SYSROOT}")
