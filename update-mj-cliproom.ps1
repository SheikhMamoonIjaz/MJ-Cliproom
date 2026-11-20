$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Read-Setting([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value.Trim().Trim('"').Trim("'") }
    $envFile = Join-Path $root ".env"
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            if ($line -match "^\s*$([regex]::Escape($Name))\s*=(.*)$") {
                return $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
    return ""
}

function Get-Health([string]$Url) {
    try { return Invoke-RestMethod -Uri "$Url/healthz" -TimeoutSec 3 }
    catch { return $null }
}

try {
    $configuredPort = Read-Setting "PEAKCUT_PORT"
    if ($configuredPort) { $preferredPort = [int]$configuredPort } else { $preferredPort = 8766 }
    $hostName = Read-Setting "PEAKCUT_HOST"
    if (-not $hostName) { $hostName = "127.0.0.1" }
    $publicUrl = Read-Setting "PEAKCUT_PUBLIC_URL"
    if (-not $publicUrl) { $publicUrl = "http://127.0.0.1:$preferredPort" }
    $baseUrl = "http://127.0.0.1:$preferredPort"
    $health = Get-Health $baseUrl

    # This owner's normal local setup uses 8766. Reuse the stock port if that is where it is already running.
    if (-not $health -and -not $configuredPort -and $preferredPort -eq 8766) {
        $fallbackHealth = Get-Health "http://127.0.0.1:8765"
        if ($fallbackHealth.app -eq "mj-cliproom") {
            $preferredPort = 8765
            $baseUrl = "http://127.0.0.1:8765"
            $health = $fallbackHealth
        }
    }

    if ($health -and $health.app -ne "mj-cliproom") {
        throw "Port $preferredPort is serving another app. Close it before updating MJ Cliproom."
    }

    if (-not $health) {
        $portBusy = Test-NetConnection -ComputerName "127.0.0.1" -Port $preferredPort -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($portBusy) { throw "Port $preferredPort is in use by another app. Close it before starting MJ Cliproom." }

        $pythonArgs = @("-m", "studio.launcher")
        $python = ""
        foreach ($candidate in @(
            (Join-Path $root ".venv\Scripts\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\MJ Cliproom\.venv\Scripts\python.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\PeakCut\.venv\Scripts\python.exe")
        )) {
            if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
        }
        if (-not $python) {
            $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
            if ($py) {
                $python = $py.Source
                $pythonArgs = @("-3", "-m", "studio.launcher")
            } else {
                $pythonCmd = Get-Command "python.exe" -ErrorAction SilentlyContinue
                if (-not $pythonCmd) { throw "Python was not found. Run install-mj-cliproom.bat first." }
                $python = $pythonCmd.Source
            }
        }

        $env:PEAKCUT_HOST = $hostName
        $env:PEAKCUT_PORT = [string]$preferredPort
        $env:PEAKCUT_PUBLIC_URL = $publicUrl
        $logDir = Join-Path $env:LOCALAPPDATA "MJ Cliproom\logs"
        $null = New-Item -ItemType Directory -Path $logDir -Force
        $null = Start-Process -FilePath $python -ArgumentList $pythonArgs -WorkingDirectory $root -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logDir "launcher.out.log") `
            -RedirectStandardError (Join-Path $logDir "launcher.err.log")
        Write-Host "Starting the supervised MJ Cliproom launcher..."
        $deadline = (Get-Date).AddMinutes(2)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 2
            $health = Get-Health $baseUrl
            if ($health.app -eq "mj-cliproom") { break }
        }
        if (-not $health -or $health.app -ne "mj-cliproom") {
            throw "MJ Cliproom did not start. Check Python and logs under $logDir, then try again."
        }
    }

    $before = $health.commit
    $beforeBoot = $health.boot
    Write-Host "Current version: $($health.version) ($($before.Substring(0, [Math]::Min(7, $before.Length))))"
    try {
        $null = Invoke-RestMethod -Uri "$baseUrl/api/update" -Method Post -ContentType "application/json" -Body "{}" -TimeoutSec 15
    } catch {
        $detail = $_.ErrorDetails.Message
        if (-not $detail) { $detail = $_.Exception.Message }
        Write-Host "The signed-in app must finish this update: $detail"
        Write-Host "Opening MJ Cliproom. Sign in if asked, then use Update now -> Install and restart."
        Start-Process "$baseUrl/app/videos"
        exit 0
    }

    Write-Host "Checking GitHub and applying the verified update..."
    $deadline = (Get-Date).AddMinutes(8)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $health = Get-Health $baseUrl
        if ($health -and $health.app -eq "mj-cliproom" -and $health.boot -ne $beforeBoot) {
            if ($health.update_install_failed) {
                throw "The update could not be installed. The previous version restarted. Check the launcher logs."
            }
            if ($health.commit -eq $before) {
                Write-Host "MJ Cliproom restarted on $($health.version)."
            } else {
                Write-Host "Updated to $($health.version) ($($health.commit.Substring(0, 7)))."
            }
            Start-Process "$baseUrl/app/videos"
            exit 0
        }
        try { $state = Invoke-RestMethod -Uri "$baseUrl/api/update" -TimeoutSec 3 }
        catch { $state = $null } # the launcher briefly stops the server while it installs
        if ($state.state -eq "error") {
            if ($state.message -match "already up to date") {
                Write-Host "MJ Cliproom is already up to date ($($health.version))."
                Start-Process "$baseUrl/app/videos"
                exit 0
            }
            throw "Update stopped: $($state.message)"
        }
    }
    throw "The updated server did not respond before the wait limit. Check the MJ Cliproom status in your browser."
} catch {
    Write-Host "MJ Cliproom updater: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
