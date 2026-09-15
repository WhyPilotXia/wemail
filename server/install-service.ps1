$ErrorActionPreference = "Stop"
$ServerDir = $PSScriptRoot
$Python = (Get-Command py).Source
$Action = New-ScheduledTaskAction -Execute $Python -Argument "wemail_udp_server.py" -WorkingDirectory $ServerDir
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "WeMail UDP Server" -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Highest -Force
Start-ScheduledTask -TaskName "WeMail UDP Server"
Write-Host "WeMail UDP Server scheduled task installed and started."
