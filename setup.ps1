param([switch]$Yes)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
git submodule update --init --recursive
if ($LASTEXITCODE) { exit $LASTEXITCODE }
if ($Yes) { & ./aruco_gps/setup.ps1 -Yes } else { & ./aruco_gps/setup.ps1 }
if ($LASTEXITCODE) { exit $LASTEXITCODE }
