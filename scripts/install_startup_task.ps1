# Installs a scheduled task in Windows Task Scheduler for current user session
# Runs Jarvis in background tray mode on user logon (non-elevated, Section 13)

$TaskName = "JarvisAssistant"
$ProjectDir = (Get-Item "$PSScriptRoot\..").FullName
$PythonwPath = "$ProjectDir\.venv\Scripts\pythonw.exe"

if (-not (Test-Path $PythonwPath)) {
    Write-Host "Virtual environment pythonw.exe not found at: $PythonwPath" -ForegroundColor Red
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $PythonwPath -Argument "-m assistant tray" -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 0)

# Unregister existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Jarvis-lite PC Operator Background Assistant"

Write-Host "Scheduled task '$TaskName' registered successfully!" -ForegroundColor Green
Write-Host "Jarvis will automatically start in system tray on user logon." -ForegroundColor Cyan
