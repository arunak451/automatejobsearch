# Registers a Windows scheduled task that runs the job digest every day at 9:00 AM.
# If the PC is off or asleep at 9:00, it runs as soon as the PC is next on.
# Run once from PowerShell:  powershell -ExecutionPolicy Bypass -File .\setup_task.ps1

$TaskName = "Daily Job Digest"
$Dir = $PSScriptRoot
$Python = (Get-Command python).Source

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Dir\job_digest.py`"" -WorkingDirectory $Dir
$Trigger = New-ScheduledTaskTrigger -Daily -At 9:00AM
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Reads job-alert emails, ranks jobs, emails the daily report. Never auto-applies." -Force

Write-Host "Scheduled '$TaskName' daily at 9:00 AM using $Python"
