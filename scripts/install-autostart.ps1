# Start the sayitship server in the background every time you log in to Windows.
# Run once from the repo folder:   .\scripts\install-autostart.ps1
# Remove it again:                 .\scripts\install-autostart.ps1 -Remove
# Logs go to data\sayitship.log.

param([switch]$Remove)

$TaskName = "sayitship"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed the '$TaskName' autostart task."
    return
}

$Repo = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    throw "Not found: $Pythonw. Create the virtual environment first (see README)."
}

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m sayitship" -WorkingDirectory $Repo
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null
Write-Host "Installed. sayitship will start at your next login."
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
