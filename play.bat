@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "SCRIPT_ROOT=%~dp0"
set "ISO_OVERRIDE="
if "%~1"=="" goto :find_installed_launcher
set "ISO_OVERRIDE=%~f1"

:find_installed_launcher
set "LAUNCHER=%SCRIPT_ROOT%out\install\clang-cl\Play Metal Gear Acid 2.bat"
if exist "%LAUNCHER%" goto :launch_installed
set "LAUNCHER=%SCRIPT_ROOT%out\install\clang-cl-software\Play Metal Gear Acid 2.bat"
if exist "%LAUNCHER%" goto :launch_installed

set "EXECUTABLE=%SCRIPT_ROOT%out\build\clang-cl\mga2.exe"
if exist "%EXECUTABLE%" goto :launch_built
set "EXECUTABLE=%SCRIPT_ROOT%out\build\clang-cl-software\mga2.exe"
if exist "%EXECUTABLE%" goto :launch_built

echo ERROR: Metal Gear Acid 2 has not been built or installed.
echo Run "%SCRIPT_ROOT%install.bat" first.
exit /b 1

:launch_installed
for %%I in ("%LAUNCHER%") do set "INSTALL_DIR=%%~dpI"
set "EXECUTABLE=%INSTALL_DIR%mga2.exe"
set "GAME_IMAGE=%INSTALL_DIR%mga2_image.bin"
if defined ISO_OVERRIDE set "PSP_ISO=%ISO_OVERRIDE%"
if not defined PSP_ISO if exist "%INSTALL_DIR%iso-path.txt" set /p "PSP_ISO="<"%INSTALL_DIR%iso-path.txt"
if defined PSP_ISO goto :installed_iso_ready
echo ERROR: No Metal Gear Acid 2 ISO was configured.
echo Pass its path as the first argument or reinstall with install.bat.
exit /b 1

:installed_iso_ready
if exist "%EXECUTABLE%" goto :installed_image_ready
echo ERROR: The installation is missing mga2.exe.
exit /b 1

:installed_image_ready
if exist "%GAME_IMAGE%" goto :installed_runtime_ready
echo ERROR: The installation is missing mga2_image.bin.
exit /b 1

:installed_runtime_ready
set "DEFAULT_MEMSTICK=%INSTALL_DIR%memstick"
set "RUN_DIR=%INSTALL_DIR%"
goto :validate_iso

:launch_built
for %%I in ("%EXECUTABLE%") do set "GAME_IMAGE=%%~dpImga2_image.bin"
if exist "%GAME_IMAGE%" goto :image_ready
echo ERROR: The generated game image was not found:
echo   %GAME_IMAGE%
echo Rebuild the game or run "%SCRIPT_ROOT%install.bat" to stage it.
exit /b 1

:image_ready
if defined ISO_OVERRIDE set "PSP_ISO=%ISO_OVERRIDE%"
if not defined PSP_ISO set "PSP_ISO=%SCRIPT_ROOT%Metal Gear Acid 2 (USA).iso"
set "DEFAULT_MEMSTICK=%SCRIPT_ROOT%memstick"
set "RUN_DIR=%SCRIPT_ROOT%"

:validate_iso
if exist "%PSP_ISO%" goto :iso_ready
echo ERROR: The supported Metal Gear Acid 2 ISO was not found:
echo   %PSP_ISO%
echo Pass its path as the first argument to play.bat.
exit /b 1

:iso_ready
if not defined SR_MEMSTICK set "SR_MEMSTICK=%DEFAULT_MEMSTICK%"
if not exist "%SR_MEMSTICK%" mkdir "%SR_MEMSTICK%"
if not errorlevel 1 goto :memstick_ready
echo ERROR: Could not create the memory-stick directory:
echo   %SR_MEMSTICK%
exit /b 1

:memstick_ready
if not defined SR_MODULE_LOG set "SR_MODULE_LOG=1"
pushd "%RUN_DIR%" >nul
if not errorlevel 1 goto :run_game
echo ERROR: Could not enter the project directory.
exit /b 1

:run_game
"%EXECUTABLE%" --configure
set "RESULT=%ERRORLEVEL%"
popd >nul
exit /b %RESULT%
