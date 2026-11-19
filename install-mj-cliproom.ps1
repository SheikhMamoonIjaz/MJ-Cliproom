$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Find-Python {
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" 
        if ($LASTEXITCODE -eq 0) { return @($py.Source, "-3.13") }
        & $py.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) { return @($py.Source, "-3") }
    }
    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if (-not $python) { throw "Python 3.10 or newer was not found. Install Python 3.13 from python.org and tick Add python.exe to PATH." }
    & $python.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Python is older than 3.10. Install Python 3.13 and run this again." }
    return @($python.Source)
}

$launch = Find-Python
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Creating .venv ..."
    $pyArgs = @()
    if ($launch.Length -gt 1) { $pyArgs = @($launch[1..($launch.Length - 1)]) }
    & $launch[0] @($pyArgs + @("-m", "venv", ".venv"))
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $venvPython)) {
        throw "The virtual environment could not be created."
    }
}
Write-Host "Installing MJ Cliproom requirements ..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip could not be updated." }
& $venvPython -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Requirements did not install. Read the message above, then run this script again." }
& $venvPython -c "import fastapi, uvicorn, httpx, numpy, sqlalchemy, soundfile, PIL, cv2, yt_dlp, sherpa_onnx, multipart; print('imports ok')"
if ($LASTEXITCODE -ne 0) { throw "A required library did not import after install." }
Write-Host "MJ Cliproom 1.2.0 is installed."
Write-Host "Start it with:  .\.venv\Scripts\python.exe -m studio.launcher"
Write-Host "Or double-click update-mj-cliproom.bat"
