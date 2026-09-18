$ErrorActionPreference = "SilentlyContinue"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$PidFile = Join-Path $Root "logs\campex.pid"
$stopped = $false

if (Test-Path $PidFile) {
    $pidValue = Get-Content $PidFile | Select-Object -First 1
    if ($pidValue) {
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Encerrando Campex pelo PID $pidValue..."
            Stop-Process -Id $pidValue -Force
            $stopped = $true
        }
    }
    Remove-Item $PidFile -Force
}

$pythonProcesses = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -match "python(.exe)?""? -m app.main" -or
        $_.CommandLine -match "python(.exe)?""?.*-m app.main"
    }

foreach ($item in $pythonProcesses) {
    Write-Host "Encerrando processo Campex PID $($item.ProcessId)..."
    Stop-Process -Id $item.ProcessId -Force
    $stopped = $true
}

if ($stopped) {
    Write-Host "Campex parada." -ForegroundColor Green
} else {
    Write-Host "Nenhuma instancia da Campex encontrada." -ForegroundColor Yellow
}
