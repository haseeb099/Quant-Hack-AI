# Start QuantAI live engine + dashboard + operator watchdog (single instance).
# Usage: powershell -ExecutionPolicy Bypass -File scripts/start_live_autonomous.ps1
param(
    [string]$Phase = "auto",
    [string]$Bridge = "auto"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "QuantAI autonomous live startup"
Write-Host "==============================="

# Stop duplicate live engines
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'main\.py.*--mode live' } |
    ForEach-Object {
        Write-Host "Stopping existing engine PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2
if (Test-Path "data\engine.lock") {
    Remove-Item "data\engine.lock" -Force -ErrorAction SilentlyContinue
}

# Toggle Algo Trading toolbar before readiness (common.ini may lag while MT5 is open)
if (Get-Process terminal64 -ErrorAction SilentlyContinue) {
    powershell -ExecutionPolicy Bypass -File "$Root\scripts\enable_mt5_algo_trading.ps1"
    Start-Sleep -Seconds 1
}

# MT5 readiness: API flags, bridge deploy, connectivity
python scripts/ensure_mt5_ready.py
if ($LASTEXITCODE -ne 0) {
    Write-Error "MT5 readiness check failed - fix MT5 login and Algo Trading, then retry."
}

# Enable Algo Trading toolbar + start ZeroMQ EA if ports closed
powershell -ExecutionPolicy Bypass -File "$Root\scripts\enable_mt5_algo_trading.ps1"
$zmqOk = $true
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $client.Connect("127.0.0.1", 32768)
    $client.Close()
} catch {
    $zmqOk = $false
}
if (-not $zmqOk) {
    Write-Host "Starting ZeroMQ bridge service..."
    powershell -ExecutionPolicy Bypass -File "$Root\scripts\start_mt5_zmq_service.ps1"
}

$env:MT5_BRIDGE = $Bridge
Write-Host ""
Write-Host "Starting live engine + dashboard on http://127.0.0.1:8080 phase=$Phase bridge=$Bridge"
Write-Host "Press Ctrl+C to stop."
python main.py --mode live --with-dashboard --phase $Phase
