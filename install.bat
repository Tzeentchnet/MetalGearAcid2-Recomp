@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_ROOT=%~dp0"
set "ISO_INPUT="
set "ISO_PATH="
set "ISO_RESULT_FILE="
set "TOOLKIT_PATH="
set "INSTALL_DIR="
set "PRESET=clang-cl"
set "SOFTWARE_ONLY=0"
set "ALLOW_UNSUPPORTED=OFF"
set "TOOLKIT_OVERRIDE="
set "PUSHED=0"
set "RESULT=1"

:parse_arguments
if "%~1"=="" goto :arguments_ready
set "CURRENT_ARGUMENT=%~1"
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
if /I "%~1"=="--software-only" goto :use_software
if /I "%~1"=="--allow-unsupported-toolkit" goto :allow_unsupported
if /I "%~1"=="--iso" goto :set_iso
if /I "%~1"=="--toolkit" goto :set_toolkit
if /I "%~1"=="--install-dir" goto :set_install_dir
if "%CURRENT_ARGUMENT:~0,1%"=="-" goto :unknown_option
if defined ISO_INPUT goto :unexpected_input
set "ISO_INPUT=%~f1"
shift
goto :parse_arguments

:unknown_option
echo ERROR: Unknown option "%~1".
echo.
call :print_usage
exit /b 2

:unexpected_input
echo ERROR: Only one positional ISO or ZIP path may be specified.
echo Use --iso PATH to provide the source explicitly.
exit /b 2

:use_software
set "SOFTWARE_ONLY=1"
set "PRESET=clang-cl-software"
shift
goto :parse_arguments

:allow_unsupported
set "ALLOW_UNSUPPORTED=ON"
set "TOOLKIT_OVERRIDE=--allow-unsupported-toolkit"
shift
goto :parse_arguments

:set_iso
if not "%~2"=="" goto :set_iso_value
echo ERROR: --iso requires a path.
exit /b 2

:set_iso_value
set "ISO_INPUT=%~f2"
shift
shift
goto :parse_arguments

:set_toolkit
if not "%~2"=="" goto :set_toolkit_value
echo ERROR: --toolkit requires a path.
exit /b 2

:set_toolkit_value
set "TOOLKIT_PATH=%~f2"
shift
shift
goto :parse_arguments

:set_install_dir
if not "%~2"=="" goto :set_install_dir_value
echo ERROR: --install-dir requires a path.
exit /b 2

:set_install_dir_value
set "INSTALL_DIR=%~f2"
shift
shift
goto :parse_arguments

:arguments_ready
if not defined ISO_INPUT set "ISO_INPUT=%SCRIPT_ROOT%Metal Gear Acid 2 (USA).iso"
if not defined TOOLKIT_PATH if defined PSP_RECOMP_DIR set "TOOLKIT_PATH=%PSP_RECOMP_DIR%"
if not defined TOOLKIT_PATH set "TOOLKIT_PATH=%SCRIPT_ROOT%..\psp-recomp"
for %%I in ("%TOOLKIT_PATH%") do set "TOOLKIT_PATH=%%~fI"
if not defined INSTALL_DIR set "INSTALL_DIR=%SCRIPT_ROOT%out\install\%PRESET%"

if not defined PSP_RECOMP_CODEGEN_CACHE if defined LOCALAPPDATA set "PSP_RECOMP_CODEGEN_CACHE=%LOCALAPPDATA%\psp-recomp\codegen-cache"
set "PSP_RECOMP_DIR=%TOOLKIT_PATH%"

pushd "%SCRIPT_ROOT%" >nul
if not errorlevel 1 goto :project_directory_ready
echo ERROR: Could not enter the project directory "%SCRIPT_ROOT%".
goto :exit

:project_directory_ready
set "PUSHED=1"

echo Metal Gear Acid 2 source installer
echo   Build:   %PRESET%
echo   Toolkit: %TOOLKIT_PATH%
echo   Source:  %ISO_INPUT%
echo   Install: %INSTALL_DIR%
echo.

echo Checking installation prerequisites...
set "PREFLIGHT_FAILED=0"
set "SOURCE_READY=1"
set "TOOLKIT_READY=1"
set "PYTHON_READY=0"
set "GIT_READY=0"
set "VISUAL_STUDIO_READY=0"
call :check_source_input
call :check_host_architecture
call :check_project_inputs
call :check_toolkit_inputs
call :check_python
call :check_source_path
call :check_git
call :check_visual_studio
call :check_build_tools
call :check_windows_sdk
call :check_vulkan_sdk
call :check_configured_paths
call :check_toolkit_identity

if "%PREFLIGHT_FAILED%"=="0" goto :preflight_ready
echo.
echo ERROR: Installation cannot continue because one or more prerequisites failed.
echo Resolve each ERROR above, then run install.bat again.
goto :exit

:preflight_ready
echo Installation prerequisite check passed.
echo.

set "ISO_RESULT_FILE=%TEMP%\mga2-iso-path-%RANDOM%-%RANDOM%.txt"
python tools\mga2\prepare_iso.py "%ISO_INPUT%" --result "%ISO_RESULT_FILE%"
if errorlevel 1 (
    set "FAILED_STEP=ISO input preparation"
    goto :command_failed
)
if exist "%ISO_RESULT_FILE%" goto :read_iso_result
echo ERROR: ISO input preparation did not return an ISO path.
goto :exit

:read_iso_result
set /p "ISO_PATH="<"%ISO_RESULT_FILE%"
del /q "%ISO_RESULT_FILE%" >nul 2>&1
set "ISO_RESULT_FILE="
if defined ISO_PATH goto :iso_path_ready
echo ERROR: ISO input preparation returned an empty ISO path.
goto :exit

:iso_path_ready

:dependencies_ready
echo [1/6] Verifying and extracting the supported ISO...
python tools\mga2\extract.py "%ISO_PATH%"
if errorlevel 1 (
    set "FAILED_STEP=ISO verification and extraction"
    goto :command_failed
)

echo.
echo [2/6] Generating native game code...
python tools\mga2\gen.py --toolkit "%TOOLKIT_PATH%" %TOOLKIT_OVERRIDE%
if errorlevel 1 (
    set "FAILED_STEP=Code generation"
    goto :command_failed
)

echo.
echo [3/6] Configuring the %PRESET% build...
cmake --preset "%PRESET%" "-DPSP_RECOMP_DIR:PATH=%TOOLKIT_PATH%" "-DMGA2_ALLOW_UNSUPPORTED_TOOLKIT:BOOL=%ALLOW_UNSUPPORTED%"
if errorlevel 1 (
    set "FAILED_STEP=CMake configuration"
    goto :command_failed
)

echo.
echo [4/6] Building Metal Gear Acid 2...
cmake --build --preset "%PRESET%" --target mga2_driver
if errorlevel 1 (
    set "FAILED_STEP=Native build"
    goto :command_failed
)

set "BUILD_DIR=%SCRIPT_ROOT%out\build\%PRESET%"
echo.
echo [5/6] Staging the runnable installation...
cmake -E make_directory "%INSTALL_DIR%"
if errorlevel 1 (
    set "FAILED_STEP=Creating the install directory"
    goto :command_failed
)
cmake -E copy_if_different "%BUILD_DIR%\mga2.exe" "%INSTALL_DIR%\mga2.exe"
if errorlevel 1 (
    set "FAILED_STEP=Copying mga2.exe"
    goto :command_failed
)
cmake -E copy_if_different "%SCRIPT_ROOT%build\mga2\gen\mga2_image.bin" "%INSTALL_DIR%\mga2_image.bin"
if errorlevel 1 (
    set "FAILED_STEP=Copying the generated game image"
    goto :command_failed
)
cmake -E copy_directory "%BUILD_DIR%\assets" "%INSTALL_DIR%\assets"
if errorlevel 1 (
    set "FAILED_STEP=Copying runtime assets"
    goto :command_failed
)
cmake -E copy_directory "%BUILD_DIR%\font" "%INSTALL_DIR%\font"
if errorlevel 1 (
    set "FAILED_STEP=Copying runtime fonts"
    goto :command_failed
)
if "%SOFTWARE_ONLY%"=="1" goto :runtime_copied
cmake -E copy_if_different "%BUILD_DIR%\SDL3.dll" "%INSTALL_DIR%\SDL3.dll"
if errorlevel 1 (
    set "FAILED_STEP=Copying SDL3.dll"
    goto :command_failed
)

:runtime_copied
cmake -E make_directory "%INSTALL_DIR%\memstick"
if errorlevel 1 (
    set "FAILED_STEP=Creating the memory-stick directory"
    goto :command_failed
)
copy /Y "tools\mga2\launch-installed.bat" "%INSTALL_DIR%\Play Metal Gear Acid 2.bat" >nul
if errorlevel 1 (
    set "FAILED_STEP=Copying the game launcher"
    goto :command_failed
)
python -c "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2] + '\n', encoding='ascii')" "%INSTALL_DIR%\iso-path.txt" "%ISO_PATH%"
if errorlevel 1 (
    set "FAILED_STEP=Recording the ISO location"
    goto :command_failed
)

echo.
echo [6/6] Installation complete.
echo   Game:     %INSTALL_DIR%\mga2.exe
echo   Launcher: %INSTALL_DIR%\Play Metal Gear Acid 2.bat
echo.
echo The ISO was verified and referenced in iso-path.txt, but it was not copied.
echo Double-click "Play Metal Gear Acid 2.bat" to start the game.
set "RESULT=0"
goto :exit

:command_failed
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" set "RESULT=1"
echo.
echo ERROR: %FAILED_STEP% failed with exit code %RESULT%.
goto :exit

:show_help
call :print_usage
exit /b 0

:print_usage
echo Usage:
echo   install.bat [ISO_OR_ZIP] [--toolkit PATH] [--install-dir PATH]
echo               [--software-only] [--allow-unsupported-toolkit]
echo   install.bat [--iso ISO_OR_ZIP] [other options]
echo.
echo Drag and drop a supported ISO or ZIP onto install.bat, or pass it as the
echo first positional argument. A ZIP must contain exactly one ISO and is
echo extracted beside the archive for installation and later gameplay. A CSO
echo or CHD image is converted once to an ISO in build\mga2\iso.
echo.
echo Options:
echo   --iso PATH          Supported ULUS-10077 USA v1.00 ISO, CSO, CHD or ZIP.
echo                       Default: "Metal Gear Acid 2 (USA).iso" beside this script.
echo   --toolkit PATH      psp-recomp checkout.
echo                       Default: PSP_RECOMP_DIR or ..\psp-recomp.
echo   --install-dir PATH  Runnable output directory.
echo                       Default: out\install\clang-cl or clang-cl-software.
echo   --software-only     Build the software reference renderer without Vulkan.
echo   --allow-unsupported-toolkit  Allow an unpinned or modified development toolkit.
echo   --help, -h          Show this help.
echo.
echo This script checks prerequisites but does not install system software.
exit /b 0

:check_source_input
if exist "%ISO_INPUT%" goto :check_source_is_file
echo ERROR: The supported USA ISO or ZIP was not found:
echo   %ISO_INPUT%
echo Drop it onto install.bat or use --iso "path\to\image.iso".
set "SOURCE_READY=0"
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_source_is_file
set "SOURCE_ATTRIBUTES="
for %%I in ("%ISO_INPUT%") do set "SOURCE_ATTRIBUTES=%%~aI"
if /I not "%SOURCE_ATTRIBUTES:~0,1%"=="d" exit /b 0
echo ERROR: The ISO input is a directory, not an ISO or ZIP file:
echo   %ISO_INPUT%
set "SOURCE_READY=0"
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_host_architecture
if /I "%PROCESSOR_ARCHITECTURE%"=="AMD64" exit /b 0
if /I "%PROCESSOR_ARCHITEW6432%"=="AMD64" exit /b 0
echo ERROR: The installer requires x64 Windows.
echo   Detected architecture: %PROCESSOR_ARCHITECTURE%
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_project_inputs
for %%F in (
    "CMakeLists.txt"
    "CMakePresets.json"
    "config\mga2.toml"
    "tools\mga2\extract.py"
    "tools\mga2\gen.py"
    "tools\mga2\local_files.py"
    "tools\mga2\prepare_iso.py"
    "tools\mga2\toolkit_identity.py"
) do if not exist "%%~F" (
    echo ERROR: The project checkout is incomplete; required file is missing:
    echo   %%~fF
    set "PREFLIGHT_FAILED=1"
)
exit /b 0

:check_toolkit_inputs
if exist "%TOOLKIT_PATH%\." goto :check_toolkit_files
echo ERROR: The psp-recomp toolkit directory was not found:
echo   %TOOLKIT_PATH%
echo Use --toolkit "path\to\psp-recomp" or set PSP_RECOMP_DIR.
set "TOOLKIT_READY=0"
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_toolkit_files
for %%F in (
    "tools\codegen.py"
    "src\rt\recomp.h"
    "src\rt\display_state.c"
    "src\rt\display_state.h"
    "src\rt\perf_stats.c"
    "src\rt\perf_stats.h"
    "src\rt\ge_patch_math.h"
    "tools\tests\ge_patch_math_test.c"
) do if not exist "%TOOLKIT_PATH%\%%~F" (
    echo ERROR: The psp-recomp checkout is incomplete; required file is missing:
    echo   %TOOLKIT_PATH%\%%~F
    set "TOOLKIT_READY=0"
    set "PREFLIGHT_FAILED=1"
)
if "%SOFTWARE_ONLY%"=="1" exit /b 0
for %%F in (
    "src\rt\texture_scaler.cpp"
    "third_party\xbrz\xbrz.cpp"
    "src\rt\gpu_d3d12\smaa.cpp"
    "src\rt\gpu_sdl3vk\shader_state.c"
    "src\rt\gpu_sdl3vk\shader_state.h"
) do if not exist "%TOOLKIT_PATH%\%%~F" (
    echo ERROR: The psp-recomp checkout lacks a required hardware-renderer file:
    echo   %TOOLKIT_PATH%\%%~F
    set "TOOLKIT_READY=0"
    set "PREFLIGHT_FAILED=1"
)
exit /b 0

:check_python
where /q python >nul 2>&1
if errorlevel 1 goto :check_python_missing
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto :check_python_version
set "PYTHON_READY=1"
exit /b 0

:check_python_missing
echo ERROR: Python 3.11 or newer was not found on PATH.
echo   Install Python 3.11+ and enable the installer's "Add Python to PATH" option.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_python_version
echo ERROR: Python 3.11 or newer is required. Detected:
python --version 2>&1
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_source_path
if not "%SOURCE_READY%"=="1" exit /b 0
if not "%PYTHON_READY%"=="1" exit /b 0
python -c "import sys; raise SystemExit(0 if sys.argv[1].isascii() else 1)" "%ISO_INPUT%" >nul 2>&1
if not errorlevel 1 exit /b 0
echo ERROR: The ISO or ZIP path must use ASCII characters:
echo   %ISO_INPUT%
echo Move it to a path such as C:\Games\MGA2.iso.
set "SOURCE_READY=0"
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_git
where /q git >nul 2>&1
if errorlevel 1 goto :check_git_missing
git --version >nul 2>&1
if errorlevel 1 goto :check_git_broken
set "GIT_READY=1"
exit /b 0

:check_git_missing
if "%ALLOW_UNSUPPORTED%"=="ON" (
    echo WARNING: Git was not found; toolkit revision checks are disabled by
    echo          --allow-unsupported-toolkit.
    exit /b 0
)
echo ERROR: Git was not found on PATH.
echo   Install Git for Windows so the toolkit revision can be verified.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_git_broken
echo ERROR: Git was found on PATH but could not be executed.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_visual_studio
if not defined VSCMD_VER goto :initialize_visual_studio
if /I not "%VSCMD_ARG_TGT_ARCH%"=="x64" goto :initialize_visual_studio
if "%VSCMD_VER:~0,3%"=="17." goto :check_visual_studio_ready

:initialize_visual_studio
call :find_vcvars64
if errorlevel 1 goto :check_visual_studio_missing
echo Initializing the Visual Studio 2022 x64 build environment...
call "%VCVARS64%" >nul
if errorlevel 1 goto :check_visual_studio_failed
if /I not "%VSCMD_ARG_TGT_ARCH%"=="x64" goto :check_visual_studio_failed
if not "%VSCMD_VER:~0,3%"=="17." goto :check_visual_studio_failed

:check_visual_studio_ready
set "VISUAL_STUDIO_READY=1"
exit /b 0

:check_visual_studio_missing
echo ERROR: Visual Studio 2022 C++ Build Tools were not found.
echo   Install the x64 C++ tools, clang-cl, and a Windows 10 or 11 SDK.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_visual_studio_failed
echo ERROR: Visual Studio 2022's vcvars64.bat failed to initialize an x64 environment.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_build_tools
call :check_cmake
call :check_ninja
call :check_clang_tools
exit /b 0

:check_cmake
where /q cmake >nul 2>&1
if errorlevel 1 goto :check_cmake_missing
set "CMAKE_VERSION="
for /f "tokens=3" %%V in ('cmake --version 2^>nul ^| findstr /b /c:"cmake version"') do set "CMAKE_VERSION=%%V"
if not defined CMAKE_VERSION goto :check_cmake_broken
for /f "tokens=1,2 delims=." %%A in ("%CMAKE_VERSION%") do call :check_cmake_version %%A %%B
if errorlevel 1 goto :check_cmake_old
exit /b 0

:check_cmake_version
if %~1 LSS 3 exit /b 1
if %~1 GTR 3 exit /b 0
if %~2 LSS 25 exit /b 1
exit /b 0

:check_cmake_missing
echo ERROR: CMake 3.25 or newer was not found on PATH.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_cmake_broken
echo ERROR: CMake was found on PATH but its version could not be determined.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_cmake_old
echo ERROR: CMake 3.25 or newer is required. Detected version %CMAKE_VERSION%.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_ninja
where /q ninja >nul 2>&1
if errorlevel 1 goto :check_ninja_missing
ninja --version >nul 2>&1
if errorlevel 1 goto :check_ninja_broken
exit /b 0

:check_ninja_missing
echo ERROR: Ninja was not found on PATH.
echo   Install Ninja and ensure ninja.exe is available on PATH.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_ninja_broken
echo ERROR: Ninja was found on PATH but could not be executed.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_clang_tools
set "CLANG_CL_PATH="
for /f "delims=" %%I in ('where clang-cl 2^>nul') do if not defined CLANG_CL_PATH set "CLANG_CL_PATH=%%I"
if not defined CLANG_CL_PATH goto :check_clang_missing
clang-cl --version >nul 2>&1
if errorlevel 1 goto :check_clang_broken
for %%I in ("%CLANG_CL_PATH%") do set "CLANG_BIN_DIR=%%~dpI"
if exist "%CLANG_BIN_DIR%llvm-lib.exe" exit /b 0
echo ERROR: llvm-lib.exe was not found beside clang-cl:
echo   %CLANG_BIN_DIR%
echo Add the LLVM tools component to Visual Studio 2022.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_clang_missing
echo ERROR: clang-cl was not found after Visual Studio initialization.
echo   Add the C++ Clang tools for Windows component to Visual Studio 2022.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_clang_broken
echo ERROR: clang-cl was found on PATH but could not be executed:
echo   %CLANG_CL_PATH%
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_windows_sdk
if not "%VISUAL_STUDIO_READY%"=="1" exit /b 0
if not defined WindowsSdkDir goto :check_windows_sdk_missing
if not defined WindowsSDKVersion goto :check_windows_sdk_missing
if not exist "%WindowsSdkDir%Include\%WindowsSDKVersion%um\Windows.h" goto :check_windows_sdk_missing
if not exist "%WindowsSdkDir%Lib\%WindowsSDKVersion%um\x64\kernel32.lib" goto :check_windows_sdk_missing
exit /b 0

:check_windows_sdk_missing
echo ERROR: An x64 Windows 10 or 11 SDK was not initialized by Visual Studio.
echo   Add a Windows SDK component in the Visual Studio Installer.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_vulkan_sdk
if "%SOFTWARE_ONLY%"=="1" exit /b 0
call :find_vulkan_sdk
if not errorlevel 1 exit /b 0
echo ERROR: A Vulkan SDK with x64 headers and libraries was not found.
if defined VULKAN_SDK echo   VULKAN_SDK currently points to "%VULKAN_SDK%".
echo Install the Vulkan SDK or use --software-only.
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_configured_paths
if not exist "%INSTALL_DIR%" goto :check_temp_path
if exist "%INSTALL_DIR%\." goto :check_temp_path
echo ERROR: The installation path exists but is not a directory:
echo   %INSTALL_DIR%
set "PREFLIGHT_FAILED=1"

:check_temp_path
if not defined TEMP goto :check_temp_missing
if exist "%TEMP%\." goto :check_codegen_cache

:check_temp_missing
echo ERROR: The TEMP directory is not configured or does not exist:
echo   %TEMP%
set "PREFLIGHT_FAILED=1"

:check_codegen_cache
if not defined PSP_RECOMP_CODEGEN_CACHE goto :check_function_catalog
if not "%PYTHON_READY%"=="1" goto :check_function_catalog
python -c "import os, pathlib, sys; path = pathlib.Path(os.path.expandvars(os.path.expanduser(sys.argv[1]))); raise SystemExit(0 if not path.exists() or path.is_dir() else 1)" "%PSP_RECOMP_CODEGEN_CACHE%" >nul 2>&1
if not errorlevel 1 goto :check_function_catalog
echo ERROR: PSP_RECOMP_CODEGEN_CACHE exists but is not a directory:
echo   %PSP_RECOMP_CODEGEN_CACHE%
set "PREFLIGHT_FAILED=1"

:check_function_catalog
if not defined PSP_RECOMP_FUNCTION_CATALOG exit /b 0
if "%PSP_RECOMP_FUNCTION_CATALOG%"=="0" exit /b 0
if not "%PYTHON_READY%"=="1" exit /b 0
python -c "import os, pathlib, sys; raise SystemExit(0 if pathlib.Path(os.path.expandvars(os.path.expanduser(sys.argv[1]))).is_file() else 1)" "%PSP_RECOMP_FUNCTION_CATALOG%" >nul 2>&1
if not errorlevel 1 exit /b 0
echo ERROR: PSP_RECOMP_FUNCTION_CATALOG does not identify an existing file:
echo   %PSP_RECOMP_FUNCTION_CATALOG%
set "PREFLIGHT_FAILED=1"
exit /b 0

:check_toolkit_identity
if not "%TOOLKIT_READY%"=="1" exit /b 0
if not "%PYTHON_READY%"=="1" exit /b 0
if "%ALLOW_UNSUPPORTED%"=="ON" goto :run_toolkit_identity
if not "%GIT_READY%"=="1" exit /b 0

:run_toolkit_identity
python tools\mga2\toolkit_identity.py --toolkit "%TOOLKIT_PATH%" %TOOLKIT_OVERRIDE%
if not errorlevel 1 exit /b 0
echo ERROR: The psp-recomp toolkit identity check failed.
set "PREFLIGHT_FAILED=1"
exit /b 0

:find_vcvars64
set "VCVARS64="

for %%E in (BuildTools Community Professional Enterprise) do if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\%%E\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS64=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\%%E\VC\Auxiliary\Build\vcvars64.bat"
if defined VCVARS64 exit /b 0

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" exit /b 1
set "VSROOT="
for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSROOT=%%I"
if not defined VSROOT exit /b 1
if not exist "%VSROOT%\VC\Auxiliary\Build\vcvars64.bat" exit /b 1
set "VCVARS64=%VSROOT%\VC\Auxiliary\Build\vcvars64.bat"
exit /b 0

:find_vulkan_sdk
if defined VULKAN_SDK if not exist "%VULKAN_SDK%\Include\vulkan\vulkan.h" exit /b 1
if defined VULKAN_SDK if not exist "%VULKAN_SDK%\Lib\vulkan-1.lib" exit /b 1
if defined VULKAN_SDK exit /b 0
if not exist "C:\VulkanSDK" exit /b 1
for /f "delims=" %%D in ('dir /b /ad /o-n "C:\VulkanSDK" 2^>nul') do if not defined VULKAN_SDK if exist "C:\VulkanSDK\%%D\Include\vulkan\vulkan.h" if exist "C:\VulkanSDK\%%D\Lib\vulkan-1.lib" set "VULKAN_SDK=C:\VulkanSDK\%%D"
if not defined VULKAN_SDK exit /b 1
exit /b 0

:exit
if defined ISO_RESULT_FILE if exist "%ISO_RESULT_FILE%" del /q "%ISO_RESULT_FILE%" >nul 2>&1
if "%PUSHED%"=="1" popd >nul
exit /b %RESULT%
