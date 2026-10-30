<#
.SYNOPSIS
    Sync the deploy copy (mt-legal-site) with a committed branch of this repo.

.DESCRIPTION
    Copies only files committed on -Ref (default: master), so .env, credentials,
    client data, and anything untracked can never reach the deploy repo.
    .claude/, CLAUDE.md and .gitignore are skipped; the deploy repo keeps its own
    .gitignore. Files the deploy repo tracks that no longer exist on -Ref are
    deleted.

    Without -Apply it only prints what would change. Nothing is committed or
    pushed: review with git status in mt-legal-site, then commit and push there.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sync_site.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\sync_site.ps1 -Apply
#>
param(
    [string]$Ref = "master",
    [string]$Site = "",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Site) { $Site = Join-Path $Root "mt-legal-site" }

if (-not (Test-Path (Join-Path $Site ".git"))) {
    throw "No git repo at $Site"
}
git -C $Root rev-parse --verify --quiet "$Ref^{commit}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Unknown ref: $Ref" }

# Paths never copied to, or deleted from, the deploy repo.
$Skip = @("CLAUDE.md", ".gitignore")
function Test-Skipped([string]$Path) {
    return ($Skip -contains $Path) -or $Path.StartsWith(".claude/")
}

$Source = @(git -C $Root ls-tree -r --name-only $Ref | Where-Object { -not (Test-Skipped $_) })
$Tracked = @(git -C $Site ls-files | Where-Object { -not (Test-Skipped $_) })
$SourceSet = @{}; foreach ($f in $Source) { $SourceSet[$f] = $true }

$Added = @(); $Changed = @()
foreach ($f in $Source) {
    $dest = Join-Path $Site $f
    if (-not (Test-Path -LiteralPath $dest)) { $Added += $f; continue }
    $want = git -C $Root rev-parse "${Ref}:$f"
    $have = git -C $Site hash-object -- $f
    if ($want -ne $have) { $Changed += $f }
}
$Removed = @($Tracked | Where-Object {
    -not $SourceSet.ContainsKey($_) -and (Test-Path -LiteralPath (Join-Path $Site $_))
})

$commit = git -C $Root log -1 --format="%h %s" $Ref
Write-Host "Source: $Ref ($commit)"
Write-Host "Target: $Site"
Write-Host ""
foreach ($f in $Added)   { Write-Host "  add     $f" -ForegroundColor Green }
foreach ($f in $Changed) { Write-Host "  update  $f" -ForegroundColor Yellow }
foreach ($f in $Removed) { Write-Host "  delete  $f" -ForegroundColor Red }
Write-Host ""
Write-Host ("{0} to add, {1} to update, {2} to delete" -f $Added.Count, $Changed.Count, $Removed.Count)

if (-not $Apply) {
    Write-Host "Preview only. Run again with -Apply to make these changes."
    return
}
if ($Added.Count + $Changed.Count + $Removed.Count -eq 0) { return }

# Export the ref through git archive so binary files are copied byte for byte.
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("mt-legal-sync-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $tar = Join-Path $tmp "export.tar"
    git -C $Root archive --format=tar --output=$tar $Ref
    if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
    $out = Join-Path $tmp "files"
    New-Item -ItemType Directory -Path $out | Out-Null
    tar -xf $tar -C $out
    if ($LASTEXITCODE -ne 0) { throw "tar failed" }

    foreach ($f in $Added + $Changed) {
        $dest = Join-Path $Site $f
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item -LiteralPath (Join-Path $out $f) -Destination $dest -Force
    }
    foreach ($f in $Removed) {
        Remove-Item -LiteralPath (Join-Path $Site $f) -Force
    }
}
finally {
    Remove-Item -Recurse -Force $tmp
}

Write-Host ""
Write-Host "Done. Review, then commit and push in the deploy repo:"
git -C $Site status --short
