param(
    [string]$PythonExe = "",
    [switch]$WithYoloRequirements
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-Python {
    param([string]$Preferred)
    $candidates = @()
    if ($Preferred) { $candidates += @{Exe = $Preferred; Args = @()} }
    $candidates += @(
        @{Exe = "py"; Args = @("-3.11")},
        @{Exe = "py"; Args = @("-3.10")},
        @{Exe = "py"; Args = @("-3.9")},
        @{Exe = "python"; Args = @()}
    )
    foreach ($candidate in $candidates) {
        try {
            $version = & $candidate.Exe @($candidate.Args + "--version") 2>$null
            if ($LASTEXITCODE -eq 0 -and $version) {
                return $candidate
            }
        } catch {
        }
    }
    throw "Python nao encontrado. Instale Python 3.11 64-bit e marque 'Add python.exe to PATH'."
}

$Python = Resolve-Python $PythonExe
Write-Step "Python encontrado"
& $Python.Exe @($Python.Args + "--version")

$VersionText = & $Python.Exe @($Python.Args + @("-c", "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))"))
$Version = [version]$VersionText
if ($Version -lt [version]"3.9") {
    throw "A Campex requer Python 3.9 ou superior. Recomendado para Windows: Python 3.11 64-bit."
}
if ($Version.Major -eq 3 -and $Version.Minor -ne 11) {
    Write-Host "Aviso: Python $Version funciona, mas o recomendado para a fabrica e Python 3.11 64-bit." -ForegroundColor Yellow
}

Write-Step "Criando ambiente virtual"
if (!(Test-Path ".venv")) {
    & $Python.Exe @($Python.Args + @("-m", "venv", ".venv"))
} else {
    Write-Host "Ambiente .venv ja existe. Mantendo." -ForegroundColor Yellow
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) {
    throw "Ambiente virtual invalido: $VenvPython nao encontrado."
}

Write-Step "Instalando dependencias Python"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
if ($WithYoloRequirements -and (Test-Path "requirements-yolo.txt")) {
    & $VenvPython -m pip install -r requirements-yolo.txt
}

Write-Step "Validando dependencias"
& $VenvPython -c "import cv2, fastapi, uvicorn, numpy; print('Dependencias principais OK')"
& $VenvPython -c "import ultralytics; print('Ultralytics/YOLO OK')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Aviso: Ultralytics/YOLO nao validou agora. A interface abre, mas a IA pode precisar de instalacao/rede/modelo." -ForegroundColor Yellow
}

Write-Step "Verificando FFmpeg"
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($null -eq $ffmpeg) {
    Write-Host "FFmpeg nao encontrado no PATH. Instale FFmpeg para melhor suporte a streams e replays." -ForegroundColor Yellow
} else {
    & ffmpeg -version | Select-Object -First 1
}

Write-Step "Criando diretorios persistentes"
@(
    "data",
    "data\evidence",
    "data\replays",
    "logs",
    "backups"
) | ForEach-Object {
    if (!(Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ | Out-Null
    }
}

Write-Step "Verificando .env"
if (!(Test-Path ".env")) {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $credentialKey = [Convert]::ToBase64String($bytes)
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        (Get-Content ".env") `
            -replace '^CAMPEX_CREDENTIAL_KEY=.*$', "CAMPEX_CREDENTIAL_KEY=$credentialKey" `
            -replace '^CAMPEX_SECRET_KEY=.*$', "CAMPEX_SECRET_KEY=$credentialKey" |
            Set-Content -Encoding UTF8 ".env"
        Write-Host ".env criado a partir de .env.example com chave local gerada. Edite credenciais antes do piloto." -ForegroundColor Yellow
    } else {
        @"
DATABASE_PATH=data/visual_ops_product.sqlite3
API_HOST=0.0.0.0
API_PORT=8000
CAMPEX_SECRET_KEY=$credentialKey
CAMPEX_CREDENTIAL_KEY=$credentialKey
CAMPEX_EMAIL_MODE=console
"@ | Set-Content -Encoding UTF8 ".env"
        Write-Host ".env criado com chave local gerada. Edite credenciais antes do piloto." -ForegroundColor Yellow
    }
} else {
    Write-Host ".env ja existe. Nao foi sobrescrito." -ForegroundColor Green
}

Write-Step "Inicializando banco local"
& $VenvPython manage.py init-db

Write-Host ""
Write-Host "Setup concluido." -ForegroundColor Green
Write-Host "Proximo passo:"
Write-Host "  .\scripts\start_factory_windows.ps1"
