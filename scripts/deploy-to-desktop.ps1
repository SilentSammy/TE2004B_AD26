[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$DesktopHost,

    [string]$DesktopRepoPath,

    [string]$Branch = "main",
    [string]$Remote = "origin"
)

$ErrorActionPreference = "Stop"

foreach ($command in @("git", "ssh")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is not installed or is not available on PATH."
    }
}

$expectedRepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location -LiteralPath $expectedRepoRoot

$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "The script is not located inside a Git repository."
}

$resolvedRepoRoot = [System.IO.Path]::GetFullPath($repoRoot)
if ($resolvedRepoRoot.TrimEnd('\') -ne $expectedRepoRoot.TrimEnd('\')) {
    throw "The script must be stored in the repository's top-level scripts directory."
}

$changes = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "Could not read the Git working-tree status." }

# This repository historically committed Python bytecode. Do not let regenerated
# cache files block a source deployment; all other local changes still do.
$meaningfulChanges = @($changes | Where-Object {
    $path = $_.Substring(3).Replace('\\', '/')
    $path -notmatch '(^|/)__pycache__/' -and $path -notmatch '\.py[cod]$'
})
if ($meaningfulChanges.Count -gt 0) {
    throw "The laptop repo has uncommitted changes. Commit them before deploying."
}

git show-ref --verify --quiet "refs/heads/$Branch"
if ($LASTEXITCODE -ne 0) { throw "Local branch '$Branch' does not exist." }

$currentBranch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $currentBranch -ne $Branch) {
    throw "Check out '$Branch' before deploying (current branch: '$currentBranch')."
}

git push $Remote $Branch
if ($LASTEXITCODE -ne 0) { throw "git push failed; the desktop was not changed." }

# Escape values for single-quoted PowerShell strings evaluated on the desktop.
$quotedBranch = $Branch.Replace("'", "''")
$quotedRemote = $Remote.Replace("'", "''")

if ([string]::IsNullOrWhiteSpace($DesktopRepoPath)) {
    $remotePathSetup = @"
`$repoPathFile = Join-Path `$env:LOCALAPPDATA 'TE2004B_AD26\repo-path.txt'
if (-not (Test-Path -LiteralPath `$repoPathFile -PathType Leaf)) {
    throw 'Desktop repository location is not registered. Run setup-desktop.cmd on the desktop first.'
}
`$desktopRepo = (Get-Content -LiteralPath `$repoPathFile -Raw).Trim()
"@
}
else {
    $quotedPath = $DesktopRepoPath.Replace("'", "''")
    $remotePathSetup = "`$desktopRepo = '$quotedPath'"
}

$remoteCommand = @"
`$ErrorActionPreference = 'Stop'
$remotePathSetup
Set-Location -LiteralPath `$desktopRepo
& .\scripts\update-desktop-repo.ps1 -Branch '$quotedBranch' -Remote '$quotedRemote'
"@

ssh $DesktopHost powershell.exe -NoProfile -ExecutionPolicy Bypass -Command $remoteCommand
if ($LASTEXITCODE -ne 0) { throw "Desktop update failed." }

Write-Host "Deployment to $DesktopHost completed."
