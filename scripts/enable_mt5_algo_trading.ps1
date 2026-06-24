# Focus MT5 and open Tools -> Options -> Expert Advisors -> enable algo trading.
$ErrorActionPreference = "Stop"
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class NativeMethods {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

$mt5 = Get-Process terminal64 -ErrorAction Stop | Select-Object -First 1
$hwnd = $mt5.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw "MT5 window not found" }

[NativeMethods]::ShowWindow($hwnd, 9) | Out-Null
[NativeMethods]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 800

Add-Type -AssemblyName System.Windows.Forms
# Tools -> Options
[System.Windows.Forms.SendKeys]::SendWait("%t")
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait("o")
Start-Sleep -Milliseconds 1200
# Expert Advisors tab (Ctrl+Tab twice from General on most MT5 builds)
[System.Windows.Forms.SendKeys]::SendWait("^{TAB}")
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait("^{TAB}")
Start-Sleep -Milliseconds 400
# Toggle first checkbox (Allow algorithmic trading) and confirm
[System.Windows.Forms.SendKeys]::SendWait(" ")
Start-Sleep -Milliseconds 200
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Start-Sleep -Milliseconds 500
# Toggle toolbar Algo Trading (common shortcut in MT5 builds)
[System.Windows.Forms.SendKeys]::SendWait("^e")
Start-Sleep -Milliseconds 500

Write-Host "Sent keyboard automation to MT5 (pid $($mt5.Id))"
