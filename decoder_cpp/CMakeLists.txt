cmake_minimum_required(VERSION 3.22)
project(spectrostream_decoder LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(BUILD_SHARED_LIB "Build shared library" ON)
option(BUILD_CLI "Build CLI executable" ON)
option(BUILD_TESTS "Build tests" ON)
option(ENABLE_SANITIZERS "Enable ASan/UBSan in Debug" ON)
option(ENABLE_GPU_DELEGATE "Enable TFLite GPU delegate (Android)" OFF)
option(ENABLE_NNAPI "Enable TFLite NNAPI delegate (Android)" OFF)

if(CMAKE_BUILD_TYPE STREQUAL "Debug" AND ENABLE_SANITIZERS)
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
endif()

# Warnings applied to our targets only (not TFLite)
set(SS_WARNINGS -Wall -Wextra -Wno-unused-parameter)

# --- TensorFlow Lite (from local source) ---
set(TENSORFLOW_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/third_party/tensorflow"
    CACHE PATH "TensorFlow source root")

set(TFLITE_ENABLE_XNNPACK ON CACHE BOOL "" FORCE)
set(TFLITE_ENABLE_EXTERNAL_DELEGATE OFF CACHE BOOL "" FORCE)
set(TFLITE_ENABLE_GPU ${ENABLE_GPU_DELEGATE} CACHE BOOL "" FORCE)
set(TFLITE_ENABLE_NNAPI ${ENABLE_NNAPI} CACHE BOOL "" FORCE)

add_subdirectory(
    "${TENSORFLOW_SOURCE_DIR}/tensorflow/lite"
    "${CMAKE_BINARY_DIR}/tflite"
    EXCLUDE_FROM_ALL
)

# --- PocketFFT C++ (header-only) ---
include(FetchContent)
FetchContent_Declare(
    pocketfft
    GIT_REPOSITORY https://github.com/mreineck/pocketfft.git
    GIT_TAG cpp
    GIT_SHALLOW ON
)
FetchContent_MakeAvailable(pocketfft)

# --- Core library (static, used by shared lib and CLI) ---
add_library(spectrostream_core STATIC
    src/sst_reader.cpp
    src/rvq_dequantizer.cpp
    src/litert_runner.cpp
    src/istft.cpp
    src/decoder.cpp
    src/wav_writer.cpp
    src/decoder_c_api.cpp
    src/cpu_affinity.cpp
)

target_include_directories(spectrostream_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    PRIVATE
        ${pocketfft_SOURCE_DIR}
)

target_compile_options(spectrostream_core PRIVATE ${SS_WARNINGS})

target_link_libraries(spectrostream_core
    PUBLIC tensorflow-lite
)

if(ENABLE_GPU_DELEGATE)
    target_compile_definitions(spectrostream_core PUBLIC SS_ENABLE_GPU_DELEGATE=1)
    target_link_libraries(spectrostream_core PUBLIC tensorflowlite_gpu_delegate)
endif()

if(ENABLE_NNAPI)
    target_compile_definitions(spectrostream_core PUBLIC SS_ENABLE_NNAPI=1)
endif()

# Android: link log library
if(ANDROID)
    target_link_libraries(spectrostream_core PUBLIC log)
endif()

# --- Shared library ---
if(BUILD_SHARED_LIB)
    add_library(spectrostream_decoder_shared SHARED
        src/decoder_c_api.cpp
    )
    target_link_libraries(spectrostream_decoder_shared PRIVATE spectrostream_core)
    target_include_directories(spectrostream_decoder_shared
        PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    )
    set_target_properties(spectrostream_decoder_shared PROPERTIES
        OUTPUT_NAME "spectrostream_decoder"
        VERSION 1.0.0
        SOVERSION 1
    )
endif()

# --- CLI executable ---
if(BUILD_CLI)
    add_executable(spectrostream_decode src/cli/main.cpp)
    target_link_libraries(spectrostream_decode PRIVATE spectrostream_core)
endif()

# --- Tests ---
if(BUILD_TESTS)
    enable_testing()
    add_executable(test_sst_reader tests/test_sst_reader.cpp)
    target_link_libraries(test_sst_reader PRIVATE spectrostream_core)
    add_test(NAME sst_reader COMMAND test_sst_reader)

    add_executable(test_rvq_dequantizer tests/test_rvq_dequantizer.cpp)
    target_link_libraries(test_rvq_dequantizer PRIVATE spectrostream_core)
    add_test(NAME rvq_dequantizer COMMAND test_rvq_dequantizer)

    add_executable(test_istft tests/test_istft.cpp)
    target_link_libraries(test_istft PRIVATE spectrostream_core)
    target_include_directories(test_istft PRIVATE ${pocketfft_SOURCE_DIR})
    add_test(NAME istft COMMAND test_istft)

    add_executable(test_c_api tests/test_c_api.c)
    target_link_libraries(test_c_api PRIVATE spectrostream_core)
    add_test(NAME c_api COMMAND test_c_api
        "${CMAKE_CURRENT_SOURCE_DIR}/models/spectrostream_decoder_core_fp32_f25.tflite"
        "${CMAKE_CURRENT_SOURCE_DIR}/models/rvq_codebooks.f32"
        "${CMAKE_CURRENT_SOURCE_DIR}/models/istft_window_f960.f32"
        "${CMAKE_CURRENT_SOURCE_DIR}/../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst"
    )
    set_tests_properties(sst_reader rvq_dequantizer istft PROPERTIES
        WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    )
endif()
