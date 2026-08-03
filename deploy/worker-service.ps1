param(
    [ValidateSet("Install", "Remove")]
    [string]$Action = "Install",
    [string]$Python = "python.exe"
)

$ErrorActionPreference = "Stop"
$taskName = "Blend Farm Worker"

if ($Action -eq "Remove") {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed $taskName"
    exit 0
}

$taskAction = New-ScheduledTaskAction -Execute $Python -Argument "-m renderfarm.worker run"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -RestartCount 100 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Description "Pulls and renders Blend Farm frames" -Force
Write-Host "Installed $taskName. Its enrollment config belongs to user $env:USERNAME."

