cmake_minimum_required(VERSION 3.25)
project(MGA2Recomp LANGUAGES C CXX)

set(MGA2_GEN_DIR "${CMAKE_SOURCE_DIR}/build/mga2/gen" CACHE PATH
    "Directory written by tools/mga2/gen.py")
set(PSP_RECOMP_DIR "D:/Github/psp-recomp" CACHE PATH
    "PSP recompiler/runtime checkout")
option(MGA2_ENABLE_D3D12 "Build the SDL3/D3D12 renderer" ON)
option(MGA2_ENABLE_VULKAN "Build the SDL3/Vulkan renderer" ON)
option(MGA2_FETCH_SDL3
       "Download the pinned SDL3 development package when it is not installed"
       ON)
option(MGA2_ENABLE_INSTRUCTION_TRACE "Keep instruction trace hooks" OFF)

if(NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/recomp.h")
  message(FATAL_ERROR "PSP_RECOMP_DIR is not a psp-recomp checkout")
endif()
if(NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/display_state.c" OR
   NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/display_state.h" OR
   NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/perf_stats.c" OR
   NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/perf_stats.h")
  message(FATAL_ERROR
    "Metal Gear Acid 2 requires psp-recomp commit 3de8644 or newer")
endif()
if(MGA2_ENABLE_D3D12 OR MGA2_ENABLE_VULKAN)
  if(NOT WIN32)
    message(FATAL_ERROR "The SDL3 hardware renderers currently require Windows")
  endif()
  if(NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/texture_scaler.cpp" OR
     NOT EXISTS "${PSP_RECOMP_DIR}/third_party/xbrz/xbrz.cpp")
    message(FATAL_ERROR
    "Hardware rendering requires psp-recomp commit 3de8644 or newer")
  endif()
  find_package(SDL3 CONFIG QUIET COMPONENTS SDL3-shared)
  if(NOT SDL3_FOUND)
    if(NOT MGA2_FETCH_SDL3)
      message(FATAL_ERROR
        "SDL3 was not found. Set SDL3_DIR or enable MGA2_FETCH_SDL3.")
    endif()
    include(FetchContent)
    FetchContent_Declare(mga2_sdl3
      URL
        "https://github.com/libsdl-org/SDL/releases/download/release-3.2.20/SDL3-devel-3.2.20-VC.zip"
      URL_HASH
        "SHA256=33968846724F8B68D58AD0B42274E00E845FB4B35C0AC88CEDBE023A755116D4"
      DOWNLOAD_EXTRACT_TIMESTAMP TRUE)
    FetchContent_GetProperties(mga2_sdl3)
    if(NOT mga2_sdl3_POPULATED)
      if(POLICY CMP0169)
        cmake_policy(PUSH)
        cmake_policy(SET CMP0169 OLD)
      endif()
      FetchContent_Populate(mga2_sdl3)
      if(POLICY CMP0169)
        cmake_policy(POP)
      endif()
    endif()
    find_path(MGA2_SDL3_CONFIG_DIR SDL3Config.cmake
      PATHS
        "${mga2_sdl3_SOURCE_DIR}/cmake"
        "${mga2_sdl3_SOURCE_DIR}/SDL3-3.2.20/cmake"
      NO_DEFAULT_PATH)
    if(NOT MGA2_SDL3_CONFIG_DIR)
      message(FATAL_ERROR
        "The pinned SDL3 package did not contain SDL3Config.cmake")
    endif()
    set(SDL3_DIR "${MGA2_SDL3_CONFIG_DIR}" CACHE PATH
        "Directory containing SDL3Config.cmake" FORCE)
    find_package(SDL3 CONFIG REQUIRED COMPONENTS SDL3-shared)
  endif()
endif()
if(MGA2_ENABLE_VULKAN)
  if(WIN32 AND NOT DEFINED Vulkan_ROOT AND "$ENV{VULKAN_SDK}" STREQUAL "")
    file(GLOB MGA2_VULKAN_SDKS LIST_DIRECTORIES TRUE "C:/VulkanSDK/*")
    list(SORT MGA2_VULKAN_SDKS COMPARE NATURAL ORDER DESCENDING)
    foreach(MGA2_VULKAN_SDK IN LISTS MGA2_VULKAN_SDKS)
      if(EXISTS "${MGA2_VULKAN_SDK}/Include/vulkan/vulkan.h")
        set(Vulkan_ROOT "${MGA2_VULKAN_SDK}")
        message(STATUS "Using Vulkan SDK ${Vulkan_ROOT}")
        break()
      endif()
    endforeach()
  endif()
  find_package(Vulkan REQUIRED)
endif()
if(CMAKE_C_COMPILER_ID STREQUAL "MSVC")
  message(FATAL_ERROR "Generated GNU C requires clang-cl, not MSVC cl")
endif()
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  get_filename_component(MGA2_CLANG_BIN_DIR "${CMAKE_C_COMPILER}" DIRECTORY)
  set(MGA2_LLVM_LIB "${MGA2_CLANG_BIN_DIR}/llvm-lib.exe")
  if(NOT EXISTS "${MGA2_LLVM_LIB}")
    message(FATAL_ERROR "llvm-lib.exe was not found beside clang-cl")
  endif()
  set(CMAKE_AR "${MGA2_LLVM_LIB}")
  set(MGA2_FP_FLAGS /fp:precise /clang:-ffp-contract=off
                    /clang:-fno-strict-aliasing)
else()
  set(MGA2_FP_FLAGS -ffp-contract=off -fno-strict-aliasing)
endif()

file(GLOB MGA2_GEN_SRCS CONFIGURE_DEPENDS
     "${MGA2_GEN_DIR}/mga2_recomp_[0-9][0-9][0-9].c")
set(MGA2_REGISTER_SRC "${MGA2_GEN_DIR}/mga2_recomp_register.c")
if(NOT EXISTS "${MGA2_REGISTER_SRC}" OR NOT MGA2_GEN_SRCS)
  message(FATAL_ERROR
    "No generated code in ${MGA2_GEN_DIR}. Run tools/mga2/gen.py first.")
endif()
list(APPEND MGA2_GEN_SRCS "${MGA2_REGISTER_SRC}")
file(GLOB_RECURSE MGA2_NATIVE_GEN_SRCS CONFIGURE_DEPENDS
     "${MGA2_GEN_DIR}/modules/*/*_recomp.c"
     "${MGA2_GEN_DIR}/modules/*/*_recomp_[0-9][0-9][0-9].c"
     "${MGA2_GEN_DIR}/modules/*/*_recomp_register.c")
if(NOT MGA2_NATIVE_GEN_SRCS)
  message(FATAL_ERROR
    "No generated native modules in ${MGA2_GEN_DIR}/modules. "
    "Run tools/mga2/gen.py first.")
endif()
list(APPEND MGA2_GEN_SRCS ${MGA2_NATIVE_GEN_SRCS})
list(LENGTH MGA2_GEN_SRCS MGA2_GEN_COUNT)
message(STATUS "MGA2 generated translation units: ${MGA2_GEN_COUNT}")

add_library(mga2_game STATIC ${MGA2_GEN_SRCS})
target_include_directories(mga2_game PRIVATE
  "${PSP_RECOMP_DIR}/src/rt" "${MGA2_GEN_DIR}")
target_compile_definitions(mga2_game PRIVATE
  "SR_ENABLE_INSTRUCTION_TRACE=$<BOOL:${MGA2_ENABLE_INSTRUCTION_TRACE}>")
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  target_compile_options(mga2_game PRIVATE /W3 ${MGA2_FP_FLAGS}
    "$<$<CONFIG:Release>:/O2>")
else()
  target_compile_options(mga2_game PRIVATE -Wall -Wno-unused-label
    ${MGA2_FP_FLAGS} "$<$<CONFIG:Release>:-O2>")
endif()

set(RT "${PSP_RECOMP_DIR}/src/rt")
set(AT3 "${PSP_RECOMP_DIR}/third_party/at3_standalone")
add_library(mga2_at3 STATIC
  ${AT3}/atrac.cpp
  ${AT3}/atrac3.cpp
  ${AT3}/atrac3plus.cpp
  ${AT3}/atrac3plusdec.cpp
  ${AT3}/atrac3plusdsp.cpp
  ${AT3}/get_bits.cpp
  ${AT3}/compat.cpp
  ${AT3}/fft.cpp
  ${AT3}/mem.cpp
  ${RT}/atrac_decode.cpp)
target_include_directories(mga2_at3 PRIVATE "${AT3}" "${RT}")
target_compile_features(mga2_at3 PRIVATE cxx_std_17)
target_compile_options(mga2_at3 PRIVATE ${MGA2_FP_FLAGS})

set(SAVEDATA_CRYPTO "${PSP_RECOMP_DIR}/third_party/ppsspp_savedata")
add_library(mga2_savedata_crypto STATIC
  ${SAVEDATA_CRYPTO}/AES.c
  ${SAVEDATA_CRYPTO}/SHA1.c
  ${SAVEDATA_CRYPTO}/bn.c
  ${SAVEDATA_CRYPTO}/ec.c
  ${SAVEDATA_CRYPTO}/kirk_engine.c
  ${SAVEDATA_CRYPTO}/chnnlsv.cpp
  ${RT}/savedata_crypto.cpp)
target_include_directories(mga2_savedata_crypto PRIVATE
  "${SAVEDATA_CRYPTO}" "${RT}")
target_compile_features(mga2_savedata_crypto PRIVATE cxx_std_17)
if(MSVC)
  target_compile_options(mga2_savedata_crypto PRIVATE /W1)
else()
  target_compile_options(mga2_savedata_crypto PRIVATE
    -Wno-unused-parameter -Wno-unused-const-variable)
endif()

set(MGA2_RUNTIME_SRCS
  ${RT}/recomp.c
  ${RT}/display_state.c
  ${RT}/dispatch_table.c
  ${RT}/fpu_mode.c
  ${RT}/fps_counter.c
  ${RT}/interp_runtime.cpp
  ${PSP_RECOMP_DIR}/src/ref/interp.cpp
  ${RT}/module.c
  ${RT}/vfpu_interp.c
  ${RT}/vfpu_asin.c
  ${RT}/perf_stats.c
  ${RT}/hle.c
  ${RT}/memstick_state.c
  ${RT}/net.c
  ${RT}/kmem.c
  ${RT}/intr.c
  ${RT}/gelist.c
  ${RT}/callback.c
  ${RT}/sched.c
  ${RT}/iso.c
  ${RT}/mpeg.c
  ${RT}/pgf.c
  ${RT}/gui.c
  ${RT}/settings_path.c
  ${RT}/graphics_config.c
  ${RT}/graphics_settings.c
  ${RT}/input_config.c
  ${RT}/input_settings.c
  ${RT}/kzl_twinstick.c
  ${RT}/startup_check.c
  ${RT}/audio_mixer.c
  ${RT}/audio_xaudio2.cpp
  ${RT}/sas_reverb.c
  ${RT}/h264_mf.c
  ${RT}/savedata.c
  ${RT}/osk_win.c
  ${RT}/ge.c)
if(MGA2_ENABLE_D3D12)
  list(APPEND MGA2_RUNTIME_SRCS
    ${RT}/gpu_d3d12/device.cpp
    ${RT}/gpu_d3d12/framebuffer.cpp
    ${RT}/gpu_d3d12/framebuffer_key.cpp
    ${RT}/gpu_d3d12/pipeline.cpp
    ${RT}/gpu_d3d12/pipeline_key.cpp
    ${RT}/gpu_d3d12/present.cpp
    ${RT}/gpu_d3d12/present_layout.cpp
    ${RT}/gpu_d3d12/shader_state.cpp
    ${RT}/gpu_d3d12/texture.cpp
    ${RT}/gpu_d3d12/texture_key.cpp
    ${RT}/gpu_d3d12/vertex.cpp)
endif()
if(MGA2_ENABLE_VULKAN)
  list(APPEND MGA2_RUNTIME_SRCS
    ${RT}/gpu_sdl3vk/sdl3vk.c
    ${RT}/gpu_sdl3vk/ge_gpu.c)
endif()
if(MGA2_ENABLE_D3D12 OR MGA2_ENABLE_VULKAN)
  list(APPEND MGA2_RUNTIME_SRCS
    ${RT}/texture_scaler.cpp
    ${PSP_RECOMP_DIR}/third_party/xbrz/xbrz.cpp)
endif()

add_executable(mga2_driver
  ${RT}/driver.c
  tools/mga2/module_policy.c
  ${MGA2_RUNTIME_SRCS})
target_include_directories(mga2_driver PRIVATE "${RT}")
target_compile_features(mga2_driver PRIVATE cxx_std_17)
target_compile_options(mga2_driver PRIVATE ${MGA2_FP_FLAGS})
target_compile_definitions(mga2_driver PRIVATE
  _CRT_SECURE_NO_WARNINGS
  SR_GAME_TITLE="Metal Gear Acid 2"
  SR_EXPECTED_ISO_SIZE=917307392
  SR_EXPECTED_ISO_SHA1="87cebe80a93c4231bdbab26ad630c6d8e2fddab5"
  SR_BOOT_ARG="disc0:/PSP_GAME/SYSDIR/EBOOT.BIN"
  SR_BOOT_NEXT_UID=0x114u
  SR_CONFIG_BOOT_IMAGE="mga2_image.bin"
  SR_CONFIG_BOOT_BASE=0x08804000u
  SR_CONFIG_BOOT_ENTRY=0x08804128u
  SR_MODULE_START_UID=0x113u
  SR_MODULE_START_PRIORITY=0x20u
  SR_MODULE_START_STACK_SIZE=0x40000u
  SR_MODULE_START_ATTR=0u
  SR_MODULE_POLICY_INIT=sr_mga2_register_module_policy
  SR_INITIAL_GE_LIST_ID=0
  SR_ENABLE_KZL_TWIN_STICK=0)
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  target_compile_options(mga2_driver PRIVATE /clang:-Wno-macro-redefined)
endif()
if(CMAKE_C_SIMULATE_ID STREQUAL "MSVC")
  target_link_options(mga2_driver PRIVATE "/MAP:$<TARGET_FILE_DIR:mga2_driver>/mga2.map")
endif()
target_link_libraries(mga2_driver PRIVATE
  mga2_game mga2_at3 mga2_savedata_crypto
  mfplat mfuuid gdi32 user32 dinput8 dxguid ole32 winmm xaudio2 bcrypt)
if(MGA2_ENABLE_D3D12)
  target_compile_definitions(mga2_driver PRIVATE SR_D3D12)
  target_link_libraries(mga2_driver PRIVATE SDL3::SDL3 d3d12 dxgi)
endif()
if(MGA2_ENABLE_VULKAN)
  target_compile_definitions(mga2_driver PRIVATE SR_SDL3VK)
  target_link_libraries(mga2_driver PRIVATE SDL3::SDL3 Vulkan::Vulkan)
endif()
if(MGA2_ENABLE_D3D12 OR MGA2_ENABLE_VULKAN)
  add_custom_command(TARGET mga2_driver POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:SDL3::SDL3-shared>
            $<TARGET_FILE_DIR:mga2_driver>)
endif()
set_target_properties(mga2_driver PROPERTIES OUTPUT_NAME mga2)
add_custom_command(TARGET mga2_driver POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_if_different
          "${MGA2_GEN_DIR}/mga2_image.bin"
          "$<TARGET_FILE_DIR:mga2_driver>/mga2_image.bin"
  COMMAND ${CMAKE_COMMAND} -E copy_directory
          "${PSP_RECOMP_DIR}/assets"
          "$<TARGET_FILE_DIR:mga2_driver>/assets"
  COMMAND ${CMAKE_COMMAND} -E copy_directory
          "${PSP_RECOMP_DIR}/font"
          "$<TARGET_FILE_DIR:mga2_driver>/font")

include(CTest)
if(BUILD_TESTING)
  add_executable(mga2_display_state_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/display_state_test.c
    ${RT}/display_state.c)
  target_include_directories(mga2_display_state_tests PRIVATE "${RT}")
  target_compile_options(mga2_display_state_tests PRIVATE ${MGA2_FP_FLAGS})
  add_test(NAME mga2_display_state COMMAND mga2_display_state_tests)

  add_executable(mga2_perf_stats_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/perf_stats_test.c
    ${RT}/perf_stats.c)
  target_include_directories(mga2_perf_stats_tests PRIVATE "${RT}")
  target_compile_options(mga2_perf_stats_tests PRIVATE ${MGA2_FP_FLAGS})
  add_test(NAME mga2_perf_stats COMMAND mga2_perf_stats_tests)

  add_executable(mga2_graphics_config_tests EXCLUDE_FROM_ALL
    ${PSP_RECOMP_DIR}/tools/tests/graphics_config_test.c
    ${RT}/graphics_config.c
    ${RT}/settings_path.c)
  target_include_directories(mga2_graphics_config_tests PRIVATE "${RT}")
  target_compile_definitions(mga2_graphics_config_tests PRIVATE
    _CRT_SECURE_NO_WARNINGS)
  target_compile_options(mga2_graphics_config_tests PRIVATE ${MGA2_FP_FLAGS})
  add_test(NAME mga2_graphics_config COMMAND mga2_graphics_config_tests)

  if(MGA2_ENABLE_D3D12 OR MGA2_ENABLE_VULKAN)
    add_executable(mga2_texture_scaler_tests EXCLUDE_FROM_ALL
      ${PSP_RECOMP_DIR}/tools/tests/texture_scaler_test.cpp
      ${RT}/texture_scaler.cpp
      ${PSP_RECOMP_DIR}/third_party/xbrz/xbrz.cpp)
    target_include_directories(mga2_texture_scaler_tests PRIVATE "${RT}")
    target_compile_features(mga2_texture_scaler_tests PRIVATE cxx_std_17)
    target_compile_options(mga2_texture_scaler_tests PRIVATE ${MGA2_FP_FLAGS})
    add_test(NAME mga2_texture_scaler COMMAND mga2_texture_scaler_tests)
  endif()

  if(MGA2_ENABLE_D3D12)
    add_executable(mga2_d3d12_vertex_tests EXCLUDE_FROM_ALL
      ${PSP_RECOMP_DIR}/tools/tests/d3d12_vertex_test.cpp
      ${RT}/gpu_d3d12/vertex.cpp
      ${RT}/gpu_d3d12/framebuffer_key.cpp
      ${RT}/gpu_d3d12/pipeline_key.cpp
      ${RT}/gpu_d3d12/shader_state.cpp
      ${RT}/gpu_d3d12/present_layout.cpp
      ${RT}/gpu_d3d12/texture_key.cpp)
    target_include_directories(mga2_d3d12_vertex_tests PRIVATE "${RT}")
    target_compile_definitions(mga2_d3d12_vertex_tests PRIVATE
      _CRT_SECURE_NO_WARNINGS)
    target_compile_features(mga2_d3d12_vertex_tests PRIVATE cxx_std_17)
    target_compile_options(mga2_d3d12_vertex_tests PRIVATE ${MGA2_FP_FLAGS})
    add_test(NAME mga2_d3d12_vertex COMMAND mga2_d3d12_vertex_tests)
  endif()
endif()
