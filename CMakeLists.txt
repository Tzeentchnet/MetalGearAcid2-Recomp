cmake_minimum_required(VERSION 3.25)
project(MGA2Recomp LANGUAGES C CXX)

set(MGA2_GEN_DIR "${CMAKE_SOURCE_DIR}/build/mga2/gen" CACHE PATH
    "Directory written by tools/mga2/gen.py")
set(PSP_RECOMP_DIR "D:/Github/psp-recomp" CACHE PATH
    "PSP recompiler/runtime checkout")
option(MGA2_ENABLE_INSTRUCTION_TRACE "Keep instruction trace hooks" OFF)

if(NOT EXISTS "${PSP_RECOMP_DIR}/src/rt/recomp.h")
  message(FATAL_ERROR "PSP_RECOMP_DIR is not a psp-recomp checkout")
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
    "$<$<CONFIG:Release>:/O1>")
else()
  target_compile_options(mga2_game PRIVATE -Wall -Wno-unused-label
    ${MGA2_FP_FLAGS} "$<$<CONFIG:Release>:-O1>")
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
  ${RT}/dispatch_table.c
  ${RT}/fpu_mode.c
  ${RT}/fps_counter.c
  ${RT}/interp_runtime.cpp
  ${PSP_RECOMP_DIR}/src/ref/interp.cpp
  ${RT}/module.c
  ${RT}/vfpu_interp.c
  ${RT}/vfpu_asin.c
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
target_link_libraries(mga2_driver PRIVATE
  mga2_game mga2_at3 mga2_savedata_crypto
  mfplat mfuuid gdi32 user32 dinput8 dxguid ole32 winmm xaudio2 bcrypt)
set_target_properties(mga2_driver PROPERTIES OUTPUT_NAME mga2)
add_custom_command(TARGET mga2_driver POST_BUILD
  COMMAND ${CMAKE_COMMAND} -E copy_directory
          "${PSP_RECOMP_DIR}/assets"
          "$<TARGET_FILE_DIR:mga2_driver>/assets"
  COMMAND ${CMAKE_COMMAND} -E copy_directory
          "${PSP_RECOMP_DIR}/font"
          "$<TARGET_FILE_DIR:mga2_driver>/font")
