# Removes the scheduled startup task for Jarvis-lite

$TaskName = "JarvisAssistant"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Scheduled task '$TaskName' removed successfully from Task Scheduler." -ForegroundColor Green
