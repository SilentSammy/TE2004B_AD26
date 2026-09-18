[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$requirementsPath = Join-Path $repoRoot "requirements.txt"
$venvPath = "$repoRoot-venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $requirementsPath -PathType Leaf)) {
    throw "requirements.txt was not found at '$requirementsPath'."
}

function Test-Python311([string]$Path) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    try {
        $version = & $Path -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        return $LASTEXITCODE -eq 0 -and $version -eq "3.11"
    }
    catch {
        return $false
    }
}

function Find-Python311 {
    $candidates = @(
        (Join-Path $env:LocalAppData "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )

    $pathPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pathPython -and $pathPython.Source -notmatch '\\WindowsApps\\') {
        $candidates += $pathPython.Source
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (Test-Python311 $candidate) {
            return $candidate
        }
    }

    return $null
}

$python = Find-Python311
if (-not $python) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.11 is missing and winget is unavailable. Install Python 3.11 from https://www.python.org/downloads/windows/ and run setup-desktop.cmd again."
    }

    Write-Host "Python 3.11 was not found. Installing it now..."
    & $winget.Source install --id Python.Python.3.11 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Python installation failed with exit code $LASTEXITCODE."
    }

    $python = Find-Python311
    if (-not $python) {
        throw "Python was installed but could not be located. Close PowerShell, reopen it, and run setup-desktop.cmd again."
    }
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Creating the Python environment at '$venvPath'..."
    & $python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}

Write-Host "Installing application dependencies..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not upgrade pip." }

& $venvPython -m pip install --requirement $requirementsPath
if ($LASTEXITCODE -ne 0) { throw "Could not install the application dependencies." }

& $venvPython -c "import cv2, inputs, numpy; assert hasattr(cv2, 'aruco')"
if ($LASTEXITCODE -ne 0) { throw "Dependency verification failed." }

Write-Host ""
Write-Host "Desktop setup is complete." -ForegroundColor Green
Write-Host "Run the application with:"
Write-Host "  $venvPython $repoRoot\main.py"
