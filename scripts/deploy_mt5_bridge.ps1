# Deploy and compile DWX_ZeroMQ_Server.mq5 into the active MT5 data folder.
param(
    [string]$Mt5Path = "C:\Program Files\MetaTrader 5",
    [string]$TerminalId = "D0E8209F77C8CF37AD8BF550E51FF075"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Root "mql5\DWX_ZeroMQ_Server.mq5"
$TargetDir = Join-Path $env:APPDATA "MetaQuotes\Terminal\$TerminalId\MQL5\Services"
$Target = Join-Path $TargetDir "DWX_ZeroMQ_Server.mq5"
$MetaEditor = Join-Path $Mt5Path "metaeditor64.exe"

if (-not (Test-Path $Source)) {
    Write-Error "Missing source EA: $Source"
}
if (-not (Test-Path $MetaEditor)) {
    Write-Error "MetaEditor not found: $MetaEditor"
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
Copy-Item -Force $Source $Target
Write-Host "Copied EA to $Target"

$log = Join-Path $TargetDir "deploy_compile.log"
& $MetaEditor /compile:"$Target" /log:"$log"

$ex5 = Join-Path $TargetDir "DWX_ZeroMQ_Server.ex5"
for ($i = 0; $i -lt 30; $i++) {
    if (Test-Path $ex5) { break }
    Start-Sleep -Milliseconds 500
}

if (Test-Path $log) {
    Get-Content $log -Tail 20
}

if (-not (Test-Path $ex5)) {
    Write-Error "Compile failed - see $log"
}

Write-Host ""
Write-Host "Compiled: $ex5"
Write-Host ""
Write-Host "Next steps in MT5:"
Write-Host '  1. Tools - Options - Expert Advisors - enable Algorithmic Trading'
Write-Host '  2. Navigator - Services - stop DWX_ZeroMQ_Server if running'
Write-Host '  3. Navigator - Services - Start DWX_ZeroMQ_Server'
Write-Host '  4. Journal should show: QuantAI ZeroMQ Server started on ports 32768-32770'
Write-Host '  5. Run: python scripts/zmq_diagnose.py'
