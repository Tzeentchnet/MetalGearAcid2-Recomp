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
if defined ISO_OVERRIDE goto :launch_installed_override
call "%LAUNCHER%"
exit /b %ERRORLEVEL%

:launch_installed_override
call "%LAUNCHER%" "%ISO_OVERRIDE%"
exit /b %ERRORLEVEL%

:launch_built
set "GAME_IMAGE=%SCRIPT_ROOT%build\mga2\gen\mga2_image.bin"
if exist "%GAME_IMAGE%" goto :image_ready
echo ERROR: The generated game image was not found:
echo   %GAME_IMAGE%
echo Run "%SCRIPT_ROOT%install.bat" to regenerate the game.
exit /b 1

:image_ready
if defined ISO_OVERRIDE set "PSP_ISO=%ISO_OVERRIDE%"
if not defined PSP_ISO set "PSP_ISO=%SCRIPT_ROOT%Metal Gear Acid 2 (USA).iso"
if exist "%PSP_ISO%" goto :iso_ready
echo ERROR: The supported Metal Gear Acid 2 ISO was not found:
echo   %PSP_ISO%
echo Pass its path as the first argument to play.bat.
exit /b 1

:iso_ready
if not defined SR_MEMSTICK set "SR_MEMSTICK=%SCRIPT_ROOT%memstick"
if not exist "%SR_MEMSTICK%" mkdir "%SR_MEMSTICK%"
if not errorlevel 1 goto :memstick_ready
echo ERROR: Could not create the memory-stick directory:
echo   %SR_MEMSTICK%
exit /b 1

:memstick_ready
if not defined SR_MODULE_LOG set "SR_MODULE_LOG=1"
pushd "%SCRIPT_ROOT%" >nul
if not errorlevel 1 goto :run_game
echo ERROR: Could not enter the project directory.
exit /b 1

:run_game
"%EXECUTABLE%" --boot "%GAME_IMAGE%" 08804000 08804128 none --gui
set "RESULT=%ERRORLEVEL%"
popd >nul
exit /b %RESULT%
