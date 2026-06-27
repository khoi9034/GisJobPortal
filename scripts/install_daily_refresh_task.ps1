$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
$TaskName = "GIS Job Portal Daily Refresh"
$Logs = Join-Path $Repo "runtime\logs"
New-Item -ItemType Directory -Force -Path $Logs | Out-Null

$Command = "Set-Location -LiteralPath '$Repo'; python scripts\refresh_jobs.py *>> 'runtime\logs\daily_refresh.log'"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"$Command`""
$Trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Description "Refresh GIS job sources and write the daily review digest." -Force | Out-Null

Write-Host "Created scheduled task: $TaskName"
Write-Host "Runs daily at 8:00 AM from: $Repo"
Write-Host "Logs: $Logs\daily_refresh.log"
Write-Host "Remove with: powershell -ExecutionPolicy Bypass -File scripts\remove_daily_refresh_task.ps1"
