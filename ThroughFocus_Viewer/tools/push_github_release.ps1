# Push ONLY current Release tree to GitHub as a single orphan commit on main.
# Replaces github main (no prior history kept). Does not create other branches.
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root
$url = (git remote get-url github).Trim()
if (-not $url) { throw "github remote missing" }

$work = Join-Path $env:TEMP ("tfv_github_orphan_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $work | Out-Null
try {
  git -C $work init -b main | Out-Null
  Copy-Item -Path (Join-Path $root "Release\*") -Destination $work -Recurse -Force
  git -C $work add -A
  git -C $work -c user.email="throughfocus-viewer@local" -c user.name="ThroughFocus_Viewer" `
    commit -m "Release: ThroughFocus_Viewer current package" | Out-Null
  $sha = git -C $work rev-parse HEAD
  Write-Host "Orphan $sha -> github main (force)"
  git -C $work push $url "HEAD:main" --force
  Write-Host "OK - GitHub has only current release tree on main."
}
finally {
  if (Test-Path $work) { Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue }
}
