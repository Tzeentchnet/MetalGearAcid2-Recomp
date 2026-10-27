@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_ROOT=%~dp0"
set "ISO_PATH="
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
if /I "%~1"=="--help" goto :show_help
if /I "%~1"=="-h" goto :show_help
if /I "%~1"=="--software-only" goto :use_software
if /I "%~1"=="--allow-unsupported-toolkit" goto :allow_unsupported
if /I "%~1"=="--iso" goto :set_iso
if /I "%~1"=="--toolkit" goto :set_toolkit
if /I "%~1"=="--install-dir" goto :set_install_dir
echo ERROR: Unknown option "%~1".
echo.
call :print_usage
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
set "ISO_PATH=%~f2"
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
if not defined ISO_PATH set "ISO_PATH=%SCRIPT_ROOT%Metal Gear Acid 2 (USA).iso"
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
echo   ISO:     %ISO_PATH%
echo   Install: %INSTALL_DIR%
echo.

if exist "%ISO_PATH%" goto :iso_ready
echo ERROR: The supported USA ISO was not found:
echo   %ISO_PATH%
echo Use --iso "path\to\Metal Gear Acid 2 (USA).iso".
goto :exit

:iso_ready
if exist "%TOOLKIT_PATH%\tools\codegen.py" goto :codegen_ready
echo ERROR: psp-recomp was not found at:
echo   %TOOLKIT_PATH%
echo Use --toolkit "path\to\psp-recomp" or set PSP_RECOMP_DIR.
goto :exit

:codegen_ready
if exist "%TOOLKIT_PATH%\src\rt\recomp.h" goto :runtime_ready
echo ERROR: The psp-recomp checkout is incomplete: src\rt\recomp.h is missing.
goto :exit

:runtime_ready
if exist "%TOOLKIT_PATH%\src\rt\display_state.c" goto :display_state_ready
echo ERROR: Metal Gear Acid 2 requires the psp-recomp commit pinned in config\mga2.toml.
echo Missing: %TOOLKIT_PATH%\src\rt\display_state.c
goto :exit

:display_state_ready
if "%SOFTWARE_ONLY%"=="1" goto :toolkit_ready
if exist "%TOOLKIT_PATH%\src\rt\texture_scaler.cpp" goto :texture_scaler_ready
echo ERROR: Hardware rendering requires the psp-recomp commit pinned in config\mga2.toml.
echo Missing: %TOOLKIT_PATH%\src\rt\texture_scaler.cpp
goto :exit

:texture_scaler_ready
if exist "%TOOLKIT_PATH%\third_party\xbrz\xbrz.cpp" goto :toolkit_ready
echo ERROR: Hardware rendering requires the psp-recomp commit pinned in config\mga2.toml.
echo Missing: %TOOLKIT_PATH%\third_party\xbrz\xbrz.cpp
goto :exit

:toolkit_ready
where /q python
if errorlevel 1 (
    echo ERROR: Python 3.11 or newer was not found on PATH.
    goto :exit
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3.11 or newer is required.
    python --version
    goto :exit
)
python -c "import sys; sys.exit(0 if sys.argv[1].isascii() else 'ERROR: The ISO path must use ASCII characters. Move the ISO to an ASCII-only path.')" "%ISO_PATH%"
if errorlevel 1 goto :exit
python tools\mga2\toolkit_identity.py --toolkit "%TOOLKIT_PATH%" %TOOLKIT_OVERRIDE%
if errorlevel 1 (
    set "FAILED_STEP=Toolkit verification"
    goto :command_failed
)

if defined VSCMD_VER if /I "%VSCMD_ARG_TGT_ARCH%"=="x64" goto :visual_studio_ready
call :find_vcvars64
if errorlevel 1 (
    echo ERROR: Visual Studio 2022 C++ Build Tools were not found.
    echo Install the x64 C++ tools, clang-cl, and a Windows SDK.
    goto :exit
)
echo Initializing the Visual Studio x64 build environment...
call "%VCVARS64%" >nul
if errorlevel 1 (
    echo ERROR: vcvars64.bat failed.
    goto :exit
)

:visual_studio_ready
where /q cmake
if errorlevel 1 (
    echo ERROR: CMake 3.25 or newer was not found on PATH.
    goto :exit
)
where /q ninja
if errorlevel 1 (
    echo ERROR: Ninja was not found on PATH.
    goto :exit
)
where /q clang-cl
if errorlevel 1 (
    echo ERROR: clang-cl was not found after initializing Visual Studio.
    goto :exit
)
where /q llvm-lib
if errorlevel 1 (
    echo ERROR: llvm-lib was not found beside the LLVM build tools.
    goto :exit
)

if "%SOFTWARE_ONLY%"=="1" goto :dependencies_ready
call :find_vulkan_sdk
if not errorlevel 1 goto :dependencies_ready
echo ERROR: A Vulkan SDK with x64 headers and libraries was not found.
if defined VULKAN_SDK echo VULKAN_SDK currently points to "%VULKAN_SDK%".
echo Install the Vulkan SDK or use --software-only.
goto :exit

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
echo   install.bat [--iso PATH] [--toolkit PATH] [--install-dir PATH]
echo               [--software-only] [--allow-unsupported-toolkit]
echo.
echo Options:
echo   --iso PATH          Supported ULUS-10077 USA v1.00 ISO.
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

:find_vcvars64
set "VCVARS64="
if defined VSINSTALLDIR if exist "%VSINSTALLDIR%VC\Auxiliary\Build\vcvars64.bat" set "VCVARS64=%VSINSTALLDIR%VC\Auxiliary\Build\vcvars64.bat"
if defined VCVARS64 exit /b 0

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
if "%PUSHED%"=="1" popd >nul
exit /b %RESULT%
