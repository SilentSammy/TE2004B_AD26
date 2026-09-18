[CmdletBinding()]
param(
    [string]$Branch = "main",
    [string]$Remote = "origin"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not installed or is not available on PATH."
}

$expectedRepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location -LiteralPath $expectedRepoRoot

$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    throw "The script is not located inside a Git repository."
}

$resolvedRepoRoot = [System.IO.Path]::GetFullPath($repoRoot)
if ($resolvedRepoRoot.TrimEnd('\') -ne $expectedRepoRoot.TrimEnd('\')) {
    throw "Refusing to clean '$resolvedRepoRoot': it is not the repository containing this script."
}

git fetch --prune $Remote
if ($LASTEXITCODE -ne 0) { throw "git fetch failed." }

git show-ref --verify --quiet "refs/remotes/$Remote/$Branch"
if ($LASTEXITCODE -ne 0) {
    throw "Remote branch '$Remote/$Branch' does not exist."
}

# Recreate the local branch at the remote commit, discarding tracked changes.
git checkout --force -B $Branch "$Remote/$Branch"
if ($LASTEXITCODE -ne 0) { throw "git checkout failed." }

git reset --hard "$Remote/$Branch"
if ($LASTEXITCODE -ne 0) { throw "git reset failed." }

# Remove every untracked/ignored file and directory. The second -f also allows
# removal of nested Git worktrees, making the checkout an exact source mirror.
git clean -ffdx
if ($LASTEXITCODE -ne 0) { throw "git clean failed." }

Write-Host "Desktop repo '$resolvedRepoRoot' now exactly matches $Remote/$Branch at $(git rev-parse --short HEAD)."
