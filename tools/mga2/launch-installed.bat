@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "INSTALL_DIR=%~dp0"
set "ISO_PATH="
if not "%~1"=="" set "ISO_PATH=%~f1"
if not defined ISO_PATH if defined PSP_ISO set "ISO_PATH=%PSP_ISO%"
if defined ISO_PATH goto :iso_ready
if exist "%INSTALL_DIR%iso-path.txt" set /p "ISO_PATH="<"%INSTALL_DIR%iso-path.txt"

:iso_ready
if not defined ISO_PATH (
    echo ERROR: No Metal Gear Acid 2 ISO was configured.
    echo Pass its path as the first argument or reinstall with install.bat.
    exit /b 1
)
if exist "%ISO_PATH%" goto :executable_ready
echo ERROR: The configured ISO was not found:
echo   %ISO_PATH%
echo Pass its current path as the first argument.
exit /b 1

:executable_ready
if exist "%INSTALL_DIR%mga2.exe" goto :image_ready
echo ERROR: The installation is missing mga2.exe.
exit /b 1

:image_ready
if exist "%INSTALL_DIR%mga2_image.bin" goto :runtime_ready
echo ERROR: The installation is missing mga2_image.bin.
exit /b 1

:runtime_ready

set "PSP_ISO=%ISO_PATH%"
if not defined SR_MEMSTICK set "SR_MEMSTICK=%INSTALL_DIR%memstick"
if not exist "%SR_MEMSTICK%" mkdir "%SR_MEMSTICK%"
if not errorlevel 1 goto :memstick_ready
echo ERROR: Could not create the memory-stick directory:
echo   %SR_MEMSTICK%
exit /b 1

:memstick_ready
if not defined SR_MODULE_LOG set "SR_MODULE_LOG=1"

pushd "%INSTALL_DIR%" >nul
if errorlevel 1 (
    echo ERROR: Could not enter the installation directory.
    exit /b 1
)
"%INSTALL_DIR%mga2.exe" --configure
set "RESULT=%ERRORLEVEL%"
popd >nul
exit /b %RESULT%
