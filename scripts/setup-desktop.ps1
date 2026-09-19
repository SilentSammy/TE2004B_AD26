[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$requirementsPath = Join-Path $repoRoot "requirements.txt"
$venvPath = Join-Path $env:LocalAppData "TE2004B_AD26\venv"
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

function Install-Python311 {
    Write-Host "Python 3.11 is not installed. Choose where to install it:"
    Write-Host "  1. Current Windows user only (no administrator password)"
    Write-Host "  2. All Windows users (administrator password required)"
    $choice = Read-Host "Selection [1]"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }
    if ($choice -notin @("1", "2")) {
        throw "Invalid selection. Run setup-desktop.cmd again and choose 1 or 2."
    }

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "This automatic installer currently supports 64-bit Windows only."
    }

    $installerUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $installerPath = Join-Path $env:TEMP "te2004b-python-3.11.9-amd64.exe"

    Write-Host "Downloading the official Python 3.11.9 installer..."
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $installerPath
        if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
            throw "The downloaded Python installer does not have a valid Python Software Foundation signature."
        }

        if ($choice -eq "1") {
            $targetDir = Join-Path $env:LocalAppData "Programs\Python\Python311"
            $arguments = @(
                "/quiet",
                "InstallAllUsers=0",
                "TargetDir=`"$targetDir`"",
                "Include_launcher=0",
                "InstallLauncherAllUsers=0",
                "PrependPath=0",
                "Include_test=0",
                "Include_pip=1"
            )
            Write-Host "Installing Python for '$env:USERNAME' only..."
            $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru
        }
        else {
            $targetDir = Join-Path $env:ProgramFiles "Python311"
            $arguments = @(
                "/quiet",
                "InstallAllUsers=1",
                "TargetDir=`"$targetDir`"",
                "Include_launcher=1",
                "InstallLauncherAllUsers=1",
                "PrependPath=1",
                "Include_test=0",
                "Include_pip=1"
            )
            Write-Host "Requesting administrator approval for an all-users installation..."
            $process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Verb RunAs -Wait -PassThru
        }

        if ($process.ExitCode -ne 0) {
            throw "Python installation failed with exit code $($process.ExitCode)."
        }
    }
    finally {
        if (Test-Path -LiteralPath $installerPath -PathType Leaf) {
            Remove-Item -LiteralPath $installerPath -Force
        }
    }
}

$python = Find-Python311
if (-not $python) {
    Install-Python311
    $python = Find-Python311
    if (-not $python) {
        throw "Python was installed but could not be located. Run setup-desktop.cmd again."
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

$stateDirectory = Join-Path $env:LocalAppData "TE2004B_AD26"
$repoPathFile = Join-Path $stateDirectory "repo-path.txt"
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
Set-Content -LiteralPath $repoPathFile -Value $repoRoot -NoNewline

Write-Host ""
Write-Host "Desktop setup is complete." -ForegroundColor Green
Write-Host "Registered repository: $repoRoot"
Write-Host "Run the application with:"
Write-Host "  .\run-app.cmd"
