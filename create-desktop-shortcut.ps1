$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop)
$ShortcutPath = Join-Path $DesktopPath "MJ-Cliping.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $root ".venv\Scripts\python.exe"
$Shortcut.Arguments = "-m studio.launcher"
$Shortcut.WorkingDirectory = $root
$Shortcut.Description = "MJ-Cliping v1.2.0 - 24/7 Autonomous AI Shorts Studio"
$Shortcut.Save()
Write-Host "Desktop shortcut created: $ShortcutPath"
