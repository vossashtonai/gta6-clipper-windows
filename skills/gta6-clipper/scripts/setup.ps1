# GTA 6 Clipper setup (Windows): checks what this PC needs, installs pinned dependencies, says when ready.
# Run: powershell -NoProfile -File setup.ps1
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest is 10x slower with the progress bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$SkillDir = Split-Path -Parent $PSScriptRoot
$Venv   = Join-Path $SkillDir ".venv"
$Models = Join-Path $SkillDir "models"
$Bin    = Join-Path $SkillDir "bin"
New-Item -ItemType Directory -Force -Path $Models, $Bin | Out-Null
$script:Failed = $false
function Ok($m)   { Write-Host "  [ok]      $m" }
function Inst($m) { Write-Host "  [install] $m" }
function Fail($m) { Write-Host "  [MISSING] $m"; $script:Failed = $true }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
}
function Find-Exe($name, $extraDirs) {
  foreach ($d in $extraDirs) { $p = Join-Path $d "$name.exe"; if (Test-Path $p) { return $p } }
  $c = Get-Command $name -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { return $c.Source }
  return $null
}
# Run a native tool quietly. (PowerShell 5.1 turns any stderr text into an error when you use 2>&1,
# and uv/pip print normal progress to stderr, so capture output to files instead.) Returns the exit code.
function Run-Quiet($exe, [string[]]$argv) {
  $o = [IO.Path]::GetTempFileName(); $e = [IO.Path]::GetTempFileName()
  $line = ($argv | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join ' '
  $p = Start-Process -FilePath $exe -ArgumentList $line -NoNewWindow -Wait -PassThru -RedirectStandardOutput $o -RedirectStandardError $e
  $code = $p.ExitCode
  if ($code -ne 0) { Get-Content $e -Tail 8 | ForEach-Object { Write-Host "            $_" } }
  Remove-Item $o, $e -Force -ErrorAction SilentlyContinue
  return $code
}
$HasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

Write-Host "GTA 6 Clipper setup (Windows)"
if (-not [Environment]::Is64BitOperatingSystem) { Write-Host "Needs 64-bit Windows 10 or 11."; exit 1 }

# 1. FFmpeg + FFprobe (cutting, encoding, loudness)
$ffDirs = @((Join-Path $Bin "ffmpeg\bin"))
$ff = Find-Exe "ffmpeg" $ffDirs
if (-not $ff -and $HasWinget) {
  Inst "FFmpeg (winget)"
  Run-Quiet "winget" @("install", "--id", "Gyan.FFmpeg", "-e", "--silent", "--accept-source-agreements", "--accept-package-agreements") | Out-Null
  Refresh-Path; $ff = Find-Exe "ffmpeg" $ffDirs
}
$fp = $null
if ($ff) { $fp = Find-Exe "ffprobe" @((Split-Path $ff)) }
if ($ff -and $fp) { Ok "FFmpeg ($ff)" } else { Fail "FFmpeg (install with winget: winget install --id Gyan.FFmpeg -e)" }

# 2. Deno (yt-dlp needs a JavaScript runtime for YouTube)
$denoDirs = @((Join-Path $env:USERPROFILE ".deno\bin"))
$deno = Find-Exe "deno" $denoDirs
if (-not $deno) {
  Inst "Deno"
  if ($HasWinget) {
    Run-Quiet "winget" @("install", "--id", "DenoLand.Deno", "-e", "--silent", "--accept-source-agreements", "--accept-package-agreements") | Out-Null
    Refresh-Path; $deno = Find-Exe "deno" $denoDirs
  }
  if (-not $deno) { Fail "Deno (install with winget: winget install --id DenoLand.Deno -e)" }
}
if ($deno) { Ok "Deno" }

# 3. uv (fast Python + venv manager; also brings Python 3.12, no system Python needed)
$uvDirs = @((Join-Path $env:USERPROFILE ".local\bin"), (Join-Path $env:USERPROFILE ".cargo\bin"))
$uv = Find-Exe "uv" $uvDirs
if (-not $uv) {
  Inst "uv"
  if ($HasWinget) {
    Run-Quiet "winget" @("install", "--id", "astral-sh.uv", "-e", "--silent", "--accept-source-agreements", "--accept-package-agreements") | Out-Null
    Refresh-Path; $uv = Find-Exe "uv" $uvDirs
  }
  if (-not $uv) { Fail "uv (install with winget: winget install --id astral-sh.uv -e)" }
}
if ($uv) { Ok "uv" }

# 4. Python environment: exact package versions and hashes are in requirements.lock.
$Py = Join-Path $Venv "Scripts\python.exe"
if ($uv) {
  # ARM laptops (Snapdragon): the speech + video libraries only ship for x64, so use x64 Python (runs emulated)
  $PyVer = "3.12"
  if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64" -or $env:PROCESSOR_ARCHITEW6432 -eq "ARM64") { $PyVer = "cpython-3.12-windows-x86_64-none"; Write-Host "  [info]    ARM PC: using x64 Python" }
  if (-not (Test-Path $Py)) { Inst "Python 3.12 environment"; Run-Quiet $uv @("venv", "--python", $PyVer, $Venv) | Out-Null }
  Inst "Pinned Python packages (hash-verified, first run downloads ~150 MB)"
  $Requirements = Join-Path $SkillDir "requirements.lock"
  $code = Run-Quiet $uv @("pip", "install", "--python", $Py, "--require-hashes", "-r", $Requirements)
  if ($code -eq 0) { Ok "Python packages (yt-dlp, faster-whisper, opencv, pillow, numpy)" } else { Fail "Python packages" }
}

# 5. Whisper model (speech -> text, runs on this PC). Downloaded once (~480 MB).
$WhisperDir = Join-Path $Models "whisper"
if (Test-Path $Py) {
  Inst "Whisper small.en model (skips if already downloaded)"
  $WhisperRevision = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"
  $code = Run-Quiet $Py @("-c", "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8', download_root=r'$WhisperDir', revision='$WhisperRevision')")
  if ($code -eq 0) { Ok "Whisper model" } else { Fail "Whisper model (check your internet and re-run)" }
}

# 6. Face detector (YuNet, ~230 KB) used to find the facecam box
$Yunet = Join-Path $Models "face_detection_yunet_2023mar.onnx"
$YunetSha256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
$YunetActual = if (Test-Path $Yunet) { (Get-FileHash -Path $Yunet -Algorithm SHA256).Hash.ToLowerInvariant() } else { "" }
if ($YunetActual -ne $YunetSha256) {
  Inst "YuNet face detector"
  $Download = "$Yunet.download"
  try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" -OutFile $Download
    $DownloadedHash = (Get-FileHash -Path $Download -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($DownloadedHash -ne $YunetSha256) { throw "YuNet SHA-256 mismatch: expected $YunetSha256, got $DownloadedHash" }
    Move-Item -Force $Download $Yunet
  } catch {
    Fail "Face detector download or verification failed: $($_.Exception.Message)"
  } finally {
    Remove-Item -Force $Download -ErrorAction SilentlyContinue
  }
}
$YunetActual = if (Test-Path $Yunet) { (Get-FileHash -Path $Yunet -Algorithm SHA256).Hash.ToLowerInvariant() } else { "" }
if ($YunetActual -eq $YunetSha256) { Ok "Face detector (SHA-256 verified)" } else { Fail "Face detector" }

# 7. Caption font (Windows ships Arial Black)
$Fonts = Join-Path $env:WINDIR "Fonts"
if ((Test-Path (Join-Path $Fonts "ariblk.ttf")) -or (Test-Path (Join-Path $Fonts "impact.ttf"))) { Ok "Caption font (Arial Black)" } else { Write-Host "  [warn]    Arial Black not found, captions use a fallback font" }

# 8. Free space
$drive = (Get-Item $SkillDir).PSDrive
$freeGB = [math]::Floor($drive.Free / 1GB)
if ($freeGB -lt 3) { Write-Host "  [warn]    Only $freeGB GB free. Each stream needs ~0.5-1 GB while it runs." } else { Ok "Disk space ($freeGB GB free)" }

# config.json: absolute tool folders so it works before Claude Code / the terminal is restarted
$dirs = @()
foreach ($x in @($ff, $deno)) { if ($x) { $dirs += (Split-Path $x) } }
$cfg = @{ whisper_model = "small.en"; whisper_revision = "d1d751a5f8271d482d14ca55d9e2deeebbae577f"; whisper_dir = $WhisperDir; yunet_model = $Yunet; path_dirs = $dirs }
[IO.File]::WriteAllText((Join-Path $SkillDir "config.json"), ($cfg | ConvertTo-Json -Compress))

if (-not $script:Failed) {
  [IO.File]::WriteAllText((Join-Path $SkillDir ".ready"), (Get-Date).ToString("s"))
  Write-Host ""; Write-Host "READY. Say: clip this stream <link>   or   find me today's biggest GTA 6 streams and clip them"
  exit 0
} else {
  Remove-Item -Force (Join-Path $SkillDir ".ready") -ErrorAction SilentlyContinue
  Write-Host ""; Write-Host "NOT READY: fix the [MISSING] items above and re-run setup."
  exit 1
}
