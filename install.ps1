# STR Secrets Content Studio installer (Windows). No admin rights, no PATH edits, nothing to
# type afterwards. Re-run any time to update or repair; it keeps your .env and the
# downloaded ffmpeg.
#
# Run it from Claude Code's Bash or PowerShell tool, or any PowerShell window:
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.ps1 | iex"
#
# What it does: copies the skill into %USERPROFILE%\.claude\skills\, finds a Python 3.9+
# (or installs one through uv, the same way the STR Secrets Connections kit does), then
# hands over to scripts\setup.py for ffmpeg, the KIE key, the balance and the launcher.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$Repo = 'Solnest-AI/str-secrets-content-studio'
$Branch = if ($env:STUDIO_BRANCH) { $env:STUDIO_BRANCH } else { 'main' }   # override to test a branch
$Name = 'str-secrets-content-studio'
$Dest = Join-Path $env:USERPROFILE ".claude\skills\$Name"
$Tmp = $null

Write-Host "STR Secrets Content Studio installer (Windows)"

# 1. The skill files: a local clone if we are running from one, else the latest zip.
$Src = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "skill\$Name\SKILL.md"))) {
    $Src = Join-Path $PSScriptRoot "skill\$Name"
}
if (-not $Src) {
    $Tmp = Join-Path $env:TEMP ("content-studio-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
    Write-Host "  downloading the skill..."
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile (Join-Path $Tmp 'repo.zip')
    } catch {
        Write-Host "ERROR: could not download the skill from GitHub ($($_.Exception.Message)). Check the internet connection and run this again."
        exit 2
    }
    Expand-Archive -Path (Join-Path $Tmp 'repo.zip') -DestinationPath $Tmp -Force
    $top = Get-ChildItem -Path $Tmp -Directory -Filter 'str-secrets-content-studio-*' | Select-Object -First 1
    if ($top) { $Src = Join-Path $top.FullName "skill\$Name" }
    if (-not $Src -or -not (Test-Path (Join-Path $Src 'SKILL.md'))) {
        Write-Host "ERROR: the download did not contain the skill folder."
        exit 2
    }
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
if (Test-Path (Join-Path $Dest 'scripts')) { Remove-Item -Recurse -Force (Join-Path $Dest 'scripts') }
Copy-Item -Path (Join-Path $Src '*') -Destination $Dest -Recurse -Force
Write-Host "  skill installed at $Dest"

# 2. A Python that works here (3.9 or newer).
function Test-Py($exe) {
    $ErrorActionPreference = 'Continue'
    if (-not $exe) { return $false }
    try {
        & $exe -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}
function Find-Py {
    $ErrorActionPreference = 'Continue'
    $c = @()
    # real installs first; the Microsoft Store alias last (it is a stub on a fresh machine)
    foreach ($n in 'python3', 'python') {
        $g = Get-Command $n -ErrorAction SilentlyContinue
        if ($g -and $g.Source -notlike '*\WindowsApps\*') { $c += $g.Source }
    }
    $pyl = Get-Command py -ErrorAction SilentlyContinue
    if ($pyl) {
        try {
            $p = & $pyl.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $c += "$p".Trim() }
        } catch {}
    }
    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    $uvs = @()
    if ($uvCmd) { $uvs += $uvCmd.Source }
    $uvs += (Join-Path $env:USERPROFILE '.local\bin\uv.exe')
    foreach ($uv in $uvs) {
        if ($uv -and (Test-Path $uv)) {
            try {
                $p = & $uv python find 3.13 2>$null
                if ($LASTEXITCODE -eq 0 -and $p) { $c += "$p".Trim() }
            } catch {}
            break
        }
    }
    foreach ($n in 'python3', 'python') {
        $g = Get-Command $n -ErrorAction SilentlyContinue
        if ($g -and $g.Source -like '*\WindowsApps\*') { $c += $g.Source }
    }
    foreach ($x in $c) { if (Test-Py $x) { return $x } }
    return $null
}

# The Claude desktop app on Windows is a Microsoft Store app: whatever it writes under AppData
# is silently redirected into its own sandbox, and `uv python install` fails in uv's default
# AppData home. Keep uv's Python under the profile, as the STR Secrets connections kit does.
if (-not $env:UV_PYTHON_INSTALL_DIR) { $env:UV_PYTHON_INSTALL_DIR = Join-Path $env:USERPROFILE '.uv\python' }
$Py = Find-Py
if (-not $Py) {
    Write-Host "  installing Python (through uv, no admin needed)..."
    $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
    if (-not (Test-Path $uv)) {
        & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
    }
    if (-not (Test-Path $uv)) {
        Write-Host "ERROR: could not install uv (https://astral.sh/uv). Check the internet connection and run this again."
        exit 2
    }
    & $uv python install 3.13 | Out-Null
    $p = & $uv python find 3.13
    if ($LASTEXITCODE -eq 0 -and $p -and (Test-Py "$p".Trim())) { $Py = "$p".Trim() }
}
if (-not $Py) {
    Write-Host "ERROR: no working Python 3.9+ was found and the automatic install failed."
    exit 2
}

# 3. Everything else (ffmpeg, the KIE key, the balance, the launcher) is setup.py's job.
& $Py (Join-Path $Dest 'scripts\setup.py')
$rc = $LASTEXITCODE
if ($Tmp) { Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue }
exit $rc
