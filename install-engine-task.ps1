# Register MJ Cliproom to start at sign-in and to be started again if it stops.
# Run from the project folder:  powershell -File install-engine-task.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
$arg = "-m studio.supervise"
$action = New-ScheduledTaskAction -Execute $python -Argument $arg -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable
Register-ScheduledTask -TaskName "MJ Cliproom" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "MJ Cliproom will start when you sign in to Windows and restart if it stops."
