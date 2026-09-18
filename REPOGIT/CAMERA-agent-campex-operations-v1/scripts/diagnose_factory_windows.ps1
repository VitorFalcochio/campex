$ErrorActionPreference = "Continue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Host "Campex - diagnostico local Windows" -ForegroundColor Cyan
Write-Host "Pasta: $Root"
Write-Host ""

Write-Host "== PowerShell =="
$PSVersionTable.PSVersion
Write-Host ""

Write-Host "== Python =="
py --version 2>$null
python --version 2>$null
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    & $VenvPython --version
} else {
    Write-Host ".venv nao encontrado."
}
Write-Host ""

Write-Host "== Arquivos principais =="
@(
    "app\main.py",
    "requirements.txt",
    ".env",
    ".venv\Scripts\python.exe",
    "scripts\setup_factory_windows.ps1",
    "scripts\start_factory_windows.ps1"
) | ForEach-Object {
    if (Test-Path $_) { Write-Host "OK  $_" -ForegroundColor Green } else { Write-Host "FALTA  $_" -ForegroundColor Red }
}
Write-Host ""

Write-Host "== Dependencias Python =="
if (Test-Path $VenvPython) {
    & $VenvPython -c "import cv2, fastapi, uvicorn, numpy; print('Dependencias principais OK')"
    & $VenvPython -c "import ultralytics; print('Ultralytics OK')" 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "Ultralytics nao importou." -ForegroundColor Yellow }
}
Write-Host ""

Write-Host "== FFmpeg =="
ffmpeg -version 2>$null | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { Write-Host "FFmpeg nao encontrado no PATH." -ForegroundColor Yellow }
Write-Host ""

Write-Host "== Porta 8000 =="
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Format-Table -AutoSize
Write-Host ""

Write-Host "== Ultimos logs =="
if (Test-Path "logs") {
    Get-ChildItem "logs" -Filter "campex-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
        Write-Host $_.FullName
        Get-Content $_.FullName -Tail 80
    }
} else {
    Write-Host "Pasta logs ainda nao existe."
}
