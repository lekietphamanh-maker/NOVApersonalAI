@echo off
setlocal
cd /d "%~dp0"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "ALFRED_DATA_DIR=%LOCALAPPDATA%\Alfred\DesktopData"
set "ALFRED_ALLOW_LEGACY_MIGRATION=1"
set "ALFRED_API_URL=http://127.0.0.1:11434"
start "" "%~dp0Nova.exe"
endlocal
