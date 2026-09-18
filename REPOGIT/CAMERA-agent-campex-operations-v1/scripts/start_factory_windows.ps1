param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$PidFile = Join-Path $Root "logs\campex.pid"

function Read-DotEnv {
    param([string]$Path)
    if (!(Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (!$line -or $line.StartsWith("#") -or !$line.Contains("=")) { return }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key -match "^[A-Za-z_][A-Za-z0-9_]*$") {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Get-LocalIPv4 {
    $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
        Where-Object {
            $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
            !$_.IPAddressToString.StartsWith("127.")
        }
    if ($addresses.Count -gt 0) {
        return $addresses[0].IPAddressToString
    }
    return "IP_DA_MAQUINA"
}

if (!(Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

if (Test-Path $PidFile) {
    $existingPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existingPid) {
        $existing = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "A Campex ja parece estar rodando. PID: $existingPid" -ForegroundColor Yellow
            Write-Host "Use .\scripts\stop_factory_windows.ps1 antes de iniciar novamente."
            exit 1
        }
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) {
    throw "Ambiente virtual nao encontrado. Rode primeiro: .\scripts\setup_factory_windows.ps1"
}

Read-DotEnv ".env"

if ($Port -le 0) {
    $Port = if ($env:API_PORT) { [int]$env:API_PORT } else { 8000 }
}

$env:API_HOST = $HostAddress
$env:API_PORT = [string]$Port
if (!$env:DATABASE_PATH) { $env:DATABASE_PATH = "data/visual_ops_product.sqlite3" }
if (!$env:CAMPEX_EDGE_ID) {
    $EdgeIdFile = Join-Path $Root "data\edge_id.txt"
    if (Test-Path $EdgeIdFile) {
        $env:CAMPEX_EDGE_ID = (Get-Content $EdgeIdFile -ErrorAction Stop | Select-Object -First 1).Trim()
    } else {
        if (!(Test-Path "data")) {
            New-Item -ItemType Directory -Path "data" | Out-Null
        }
        $generatedEdgeId = "edge_" + ([guid]::NewGuid().ToString("N").Substring(0, 12))
        Set-Content -Path $EdgeIdFile -Value $generatedEdgeId -Encoding ASCII
        $env:CAMPEX_EDGE_ID = $generatedEdgeId
    }
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $Root "logs\campex-$timestamp.log"
$LocalIp = Get-LocalIPv4

Write-Host ""
Write-Host "Campex iniciando..." -ForegroundColor Cyan
Write-Host "Localhost: http://127.0.0.1:$Port"
Write-Host "Rede local: http://$LocalIp`:$Port"
Write-Host "Edge ID: $env:CAMPEX_EDGE_ID"
Write-Host "Log: $LogFile"
Write-Host ""
Write-Host "Nao exponha esta porta na internet. Use apenas na rede local da fabrica." -ForegroundColor Yellow
Write-Host "Pressione Ctrl+C para encerrar com seguranca."
Write-Host ""

Set-Content -Path $PidFile -Value $PID -Encoding ASCII

try {
    & $VenvPython manage.py run-edge-production --edge-id $env:CAMPEX_EDGE_ID --host $HostAddress --port $Port 2>&1 | Tee-Object -FilePath $LogFile -Append
    exit $LASTEXITCODE
}
finally {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
