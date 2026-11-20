@echo off
setlocal
cd /d "%~dp0"
set "ALFRED_DATA_DIR=%~dp0Data"
set "ALFRED_PORTABLE_OLLAMA=1"
set "ALFRED_PORTABLE_EDITION=1"
set "ALFRED_OLLAMA_EXE=%~dp0Ollama\ollama.exe"
set "OLLAMA_MODELS=%~dp0Ollama\models"
set "OLLAMA_HOST=127.0.0.1:11435"
set "OLLAMA_NO_CLOUD=1"
set "ALFRED_API_URL=http://127.0.0.1:11435"
set "ALFRED_MODEL=qwen2.5:7b"
start "" "%~dp0Nova.exe"
endlocal
