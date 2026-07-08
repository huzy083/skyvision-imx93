cmake_minimum_required(VERSION 3.16)
project(skyvision_ui VERSION 0.2 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# Build options (default ON; turned off automatically if libs are missing).
option(WITH_TFLITE    "NPU detection via TensorFlow Lite + Ethos-U delegate" ON)
option(WITH_MOSQUITTO "MQTT publish/subscribe via libmosquitto"              ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Quick QuickControls2)
qt_standard_project_setup()

find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0)

set(SKYVISION_SOURCES
    src/main.cpp
    src/AppController.cpp
    src/AppController.h
    src/GstRunner.cpp
    src/GstRunner.h
    src/PlaybackRunner.cpp
    src/PlaybackRunner.h
    src/CameraManager.cpp
    src/CameraManager.h
    src/MqttPublisher.cpp
    src/MqttPublisher.h
    src/WifiManager.cpp
    src/WifiManager.h
    src/BatteryMonitor.cpp
    src/BatteryMonitor.h
    src/Tracker.cpp
    src/Tracker.h
    src/ScreenRecorder.cpp
    src/ScreenRecorder.h
    src/VideoItem.h
    src/Detection.h
    src/Config.h
)

# NOTE: QML is intentionally loaded from disk at runtime (SKYVISION_QML_DIR,
# default /root/ui-qml) so the .qml files stay the single source of truth and
# can be edited without recompiling — matching the previous Python workflow.
# We deliberately do NOT use qt_add_qml_module here.
qt_add_executable(skyvision_ui ${SKYVISION_SOURCES})

# We load QML from disk at runtime and don't use qt_add_qml_module, so skip the
# build-time qmlimportscanner pass (QML plugins resolve dynamically on-device).
set_target_properties(skyvision_ui PROPERTIES QT_QML_MODULE_NO_IMPORT_SCAN ON)

target_link_libraries(skyvision_ui PRIVATE
    Qt6::Core Qt6::Gui Qt6::Quick Qt6::QuickControls2
    PkgConfig::GST
)

# ---- optional: TensorFlow Lite + Ethos-U delegate ----
if(WITH_TFLITE)
    find_path(TFLITE_INCLUDE_DIR tensorflow/lite/c/c_api.h)
    find_library(TFLITE_LIB NAMES tensorflow-lite tensorflowlite)
    if(TFLITE_INCLUDE_DIR AND TFLITE_LIB)
        target_sources(skyvision_ui PRIVATE
            src/Detector.cpp src/Detector.h
            src/InferenceWorker.cpp src/InferenceWorker.h)
        target_compile_definitions(skyvision_ui PRIVATE HAVE_TFLITE)
        target_include_directories(skyvision_ui PRIVATE ${TFLITE_INCLUDE_DIR})
        target_link_libraries(skyvision_ui PRIVATE ${TFLITE_LIB})
        message(STATUS "TFLite found: ${TFLITE_LIB} -> NPU detection ENABLED")
    else()
        message(WARNING "TFLite not found -> NPU detection DISABLED (video still works)")
    endif()
endif()

# ---- optional: libmosquitto ----
if(WITH_MOSQUITTO)
    pkg_check_modules(MOSQ IMPORTED_TARGET libmosquitto)
    if(MOSQ_FOUND)
        target_compile_definitions(skyvision_ui PRIVATE HAVE_MOSQUITTO)
        target_link_libraries(skyvision_ui PRIVATE PkgConfig::MOSQ)
        message(STATUS "libmosquitto found -> MQTT ENABLED")
    else()
        message(WARNING "libmosquitto not found -> MQTT DISABLED (stubbed)")
    endif()
endif()

install(TARGETS skyvision_ui RUNTIME DESTINATION bin)
