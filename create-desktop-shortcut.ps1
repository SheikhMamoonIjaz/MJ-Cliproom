$ErrorActionPreference = "SilentlyContinue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$WshShell = New-Object -ComObject WScript.Shell

$desktopPaths = @(
    [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::Desktop),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "OneDrive\Desktop")
) | Select-Object -Unique | Where-Object { Test-Path $_ }

$startBat = Join-Path $root "Start-MJ-Cliproom.bat"
$updateBat = Join-Path $root "update-mj-cliproom.bat"

foreach ($dp in $desktopPaths) {
    # 1. Main App Launcher Shortcut
    $shortcutPath = Join-Path $dp "MJ-Cliping.lnk"
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $startBat
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "MJ-Cliping v1.2.2 - 24/7 Autonomous AI Shorts Studio"
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $shortcutPath"

    # 2. Modern Start Server Shortcut
    $startServerPath = Join-Path $dp "MJ Cliproom - Start Server.lnk"
    $startServer = $WshShell.CreateShortcut($startServerPath)
    $startServer.TargetPath = $startBat
    $startServer.WorkingDirectory = $root
    $startServer.Description = "Start MJ Cliproom v1.2.2 - 24/7 AI Shorts Studio"
    $startServer.Save()

    # 3. Modern Supervised Updater Shortcut
    $updaterPath = Join-Path $dp "MJ Cliproom Updater.lnk"
    $updater = $WshShell.CreateShortcut($updaterPath)
    $updater.TargetPath = $updateBat
    $updater.WorkingDirectory = $root
    $updater.Description = "Update MJ Cliproom to the latest release"
    $updater.Save()

    # 4. Direct batch launcher on desktop
    $desktopBat = Join-Path $dp "Start-MJ-Cliproom.bat"
    Copy-Item -Path $startBat -Destination $desktopBat -Force

    # Clean up obsolete beta 0.10 shortcut name if present
    $oldBeta = Join-Path $dp "MJ Cliproom Beta 0.10 - Start Server.lnk"
    if (Test-Path $oldBeta) {
        Remove-Item -Path $oldBeta -Force -ErrorAction SilentlyContinue
    }
}
