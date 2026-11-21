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
    $shortcutPath = Join-Path $dp "MJ Cliproom.lnk"
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $startBat
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "Launch MJ Cliproom 2.0.0"
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $shortcutPath"

    # 2. Modern Start Server Shortcut
    $startServerPath = Join-Path $dp "MJ Cliproom - Start Server.lnk"
    $startServer = $WshShell.CreateShortcut($startServerPath)
    $startServer.TargetPath = $startBat
    $startServer.WorkingDirectory = $root
    $startServer.Description = "Start the local MJ Cliproom server"
    $startServer.Save()

    # 3. Modern Supervised Updater Shortcut
    $updaterPath = Join-Path $dp "MJ Cliproom Updater.lnk"
    $updater = $WshShell.CreateShortcut($updaterPath)
    $updater.TargetPath = $updateBat
    $updater.WorkingDirectory = $root
    $updater.Description = "Update MJ Cliproom to the latest release"
    $updater.Save()

    # Clean up obsolete shortcut names if present
    foreach ($oldName in @("MJ Cliproom Beta 0.10 - Start Server.lnk", "MJ-Cliping.lnk")) {
        $oldPath = Join-Path $dp $oldName
        if (Test-Path $oldPath) {
            Remove-Item -Path $oldPath -Force -ErrorAction SilentlyContinue
        }
    }
}
