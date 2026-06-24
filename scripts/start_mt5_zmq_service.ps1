# Stop any stuck DWX service, then start the compiled ZeroMQ bridge in MT5.
param(
    [string]$Mt5Path = "C:\Program Files\MetaTrader 5",
    [string]$TerminalId = "D0E8209F77C8CF37AD8BF550E51FF075"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Ex5 = Join-Path $env:APPDATA "MetaQuotes\Terminal\$TerminalId\MQL5\Services\DWX_ZeroMQ_Server.ex5"
$Terminal = Join-Path $Mt5Path "terminal64.exe"

if (-not (Test-Path $Ex5)) {
    Write-Error "Missing compiled service: $Ex5`nRun scripts/deploy_mt5_bridge.ps1 first."
}

function Test-ZmqPort([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

# Release stuck listeners by restarting MT5 when ports are held but the service is dead.
$portsBusy = (Test-ZmqPort 32768) -and (Test-ZmqPort 32769) -and (Test-ZmqPort 32770)
$mt5 = Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -First 1
if ($portsBusy -and $mt5) {
    Write-Host "Restarting MT5 to release ZeroMQ ports (PID $($mt5.Id))..."
    Stop-Process -Id $mt5.Id -Force
    Start-Sleep -Seconds 4
}

if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
    Write-Host "Starting MetaTrader 5..."
    Start-Process $Terminal
    Start-Sleep -Seconds 12
}

$mt5 = Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $mt5) {
    Write-Error "MetaTrader 5 is not running."
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NativeMethods {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

$hwnd = $mt5.MainWindowHandle
if ($hwnd -ne [IntPtr]::Zero) {
    [NativeMethods]::ShowWindow($hwnd, 9) | Out-Null
    [NativeMethods]::SetForegroundWindow($hwnd) | Out-Null
    Start-Sleep -Milliseconds 800
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait("^e")
    Start-Sleep -Milliseconds 500
}

Write-Host "Launching DWX_ZeroMQ_Server service..."
Start-Process $Ex5
Start-Sleep -Seconds 5

for ($i = 1; $i -le 12; $i++) {
    if ((Test-ZmqPort 32768) -and (Test-ZmqPort 32769) -and (Test-ZmqPort 32770)) {
        Write-Host "ZeroMQ ports 32768-32770 are listening."
        break
    }
    Start-Sleep -Seconds 1
}

Push-Location $Root
python scripts/zmq_diagnose.py
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) {
    Write-Host ""
    Write-Host "If diagnose failed: MT5 -> Navigator -> Services -> Stop all DWX_ZeroMQ_Server instances, then run this script again."
    exit $code
}

Write-Host "ZeroMQ bridge is running."
