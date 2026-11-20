# Fills this USB Edition with Ollama and two models (7b, and 3b for weaker PCs). Run it from the USB drive itself.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # the progress bar makes downloads many times slower
$ollama = Join-Path $PSScriptRoot "Ollama"
Write-Host "This downloads about 8.5 GB onto this drive: Ollama (1.6 GB), AMD GPU support (0.3 GB), qwen2.5:7b (4.7 GB) and qwen2.5:3b (1.9 GB) for weaker PCs. Nova picks the one that fits each PC."
Write-Host "Have the old Nova USB Edition? Copy its Ollama folder here instead, then close this window."
if ((Read-Host "Download now? (y/n)") -ne "y") { exit 1 }
if (-not (Test-Path (Join-Path $ollama "ollama.exe"))) {
  foreach ($zip in "ollama-windows-amd64.zip", "ollama-windows-amd64-rocm.zip") {
    $file = Join-Path $env:TEMP $zip
    Write-Host "Downloading $zip ..."
    Invoke-WebRequest "https://github.com/ollama/ollama/releases/latest/download/$zip" -OutFile $file
    Expand-Archive $file -DestinationPath $ollama -Force
    Remove-Item $file
  }
}
$env:OLLAMA_MODELS = Join-Path $ollama "models"
$env:OLLAMA_HOST = "127.0.0.1:11435"
$server = Start-Process (Join-Path $ollama "ollama.exe") -ArgumentList "serve" -WindowStyle Hidden -PassThru
try {
  Start-Sleep -Seconds 4
  foreach ($model in "qwen2.5:7b", "qwen2.5:3b") {
    & (Join-Path $ollama "ollama.exe") pull $model
    if ($LASTEXITCODE -ne 0) { throw "The $model download failed. Run this again to resume." }
  }
} finally {
  Stop-Process -Id $server.Id -ErrorAction SilentlyContinue
}
Write-Host "Done. Double-click 'Start Nova USB.bat'."
