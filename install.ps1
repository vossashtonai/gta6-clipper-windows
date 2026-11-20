# GTA 6 Clipper for Windows: install from a locally checked-out repository.
# Review the source, then run: .\install.ps1
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "Installing GTA 6 Clipper for Windows..."
$Skills = Join-Path $env:USERPROFILE ".claude\skills"
$Src = Join-Path $PSScriptRoot "skills"
foreach ($name in @("gta6-clipper", "gta6-live-clipper")) {
  if (-not (Test-Path (Join-Path $Src $name) -PathType Container)) {
    throw "Required skill source is missing: $(Join-Path $Src $name)"
  }
}

New-Item -ItemType Directory -Force -Path $Skills | Out-Null
foreach ($name in @("gta6-clipper", "gta6-live-clipper")) {
  $dst = Join-Path $Skills $name
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  # copy the skill files over the top: keeps an existing .venv / models / .env, replaces old Mac files
  Copy-Item -Recurse -Force (Join-Path $Src "$name\*") $dst
  $old = Join-Path $dst "scripts\setup.sh"
  if (Test-Path $old) { Remove-Item -Force $old }   # left over from the Mac version
  Write-Host "  [ok]      skill $name -> $dst"
}

$ErrorActionPreference = "Continue"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Skills "gta6-clipper\scripts\setup.ps1")
if ($LASTEXITCODE -eq 0) {
  Write-Host ""
  Write-Host "Done. Close and reopen Claude Code, then say: clip this stream <link>"
} else {
  Write-Host ""
  Write-Host "Setup didn't finish. Copy everything above and send it to Claude Code (or post it in the Skool community)."
}
