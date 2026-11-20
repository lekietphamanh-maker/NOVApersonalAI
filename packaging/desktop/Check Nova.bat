@echo off
setlocal
cd /d "%~dp0"
if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "ALFRED_DATA_DIR=%LOCALAPPDATA%\Alfred\CheckData"
set "ALFRED_API_URL=http://127.0.0.1:11434"
"%~dp0Nova.exe" --check
if errorlevel 1 (echo Nova check failed. Ensure Ollama is running and the model it names is installed.) else (echo Nova runtime, bundled Vosk model and recognizer, audio endpoint enumeration, and the model picked for this PC passed the local check. Screen UI Automation is optional and loads only when requested.)
endlocal
