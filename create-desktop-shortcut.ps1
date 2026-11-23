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
$icoPath = Join-Path $root "web\brand\mj-cliproom.ico"

$targetFolders = @(
    $desktopPaths
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
) | Select-Object -Unique | Where-Object { Test-Path $_ }

foreach ($dp in $desktopPaths) {
    # 1. Main App Launcher Shortcut
    $shortcutPath = Join-Path $dp "MJ Cliproom.lnk"
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $startBat
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = "Launch MJ Cliproom 2.0.0 Workstation (http://localhost:8766)"
    if (Test-Path -LiteralPath $icoPath) { $shortcut.IconLocation = "$icoPath,0" }
    $shortcut.Save()
    Write-Host "Updated shortcut: $shortcutPath"

    # 2. Modern Start Server Shortcut
    $startServerPath = Join-Path $dp "MJ Cliproom - Start Server.lnk"
    $startServer = $WshShell.CreateShortcut($startServerPath)
    $startServer.TargetPath = $startBat
    $startServer.WorkingDirectory = $root
    $startServer.Description = "Start the local MJ Cliproom 2.0.0 server"
    if (Test-Path -LiteralPath $icoPath) { $startServer.IconLocation = "$icoPath,0" }
    $startServer.Save()
    Write-Host "Updated shortcut: $startServerPath"

    # 3. Modern Supervised Updater Shortcut
    $updaterPath = Join-Path $dp "MJ Cliproom Updater.lnk"
    $updater = $WshShell.CreateShortcut($updaterPath)
    $updater.TargetPath = $updateBat
    $updater.WorkingDirectory = $root
    $updater.Description = "Update MJ Cliproom 2.0.0 to the latest release"
    if (Test-Path -LiteralPath $icoPath) { $updater.IconLocation = "$icoPath,0" }
    $updater.Save()
    Write-Host "Updated shortcut: $updaterPath"

    # Clean up obsolete shortcut names if present
    foreach ($oldName in @("MJ Cliproom Beta 0.10 - Start Server.lnk", "MJ-Cliping.lnk", "PeakCut.lnk")) {
        $oldPath = Join-Path $dp $oldName
        if (Test-Path $oldPath) {
            Remove-Item -Path $oldPath -Force -ErrorAction SilentlyContinue
        }
    }
}

$startMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (Test-Path -LiteralPath $startMenuDir) {
    $smPath = Join-Path $startMenuDir "MJ Cliproom.lnk"
    $sm = $WshShell.CreateShortcut($smPath)
    $sm.TargetPath = $startBat
    $sm.WorkingDirectory = $root
    $sm.Description = "Launch MJ Cliproom 2.0.0 Workstation"
    if (Test-Path -LiteralPath $icoPath) { $sm.IconLocation = "$icoPath,0" }
    $sm.Save()
    Write-Host "Updated Start Menu shortcut: $smPath"
}
