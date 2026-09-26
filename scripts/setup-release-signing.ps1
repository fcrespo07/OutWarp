<#
.SYNOPSIS
  Prepare a Windows 10/11 machine to sign and publish OutWarp releases.

.DESCRIPTION
  Installs (per user, via winget) what the release steps need: Git, GitHub CLI,
  Python and minisign, then makes sure gh is logged in.

  With -NewKeys it also generates the release keypairs, which is only needed
  when the keys are replaced (see docs/RELEASE_SIGNING.md):
    - primary: signs every release, %USERPROFILE%\.minisign\outwarp-release.key
    - backup:  trusted by the updaters too, but its secret half is moved to
               offline storage and only used if the primary is ever lost.
  Both .pub files are written to the repository root, and the script prints a
  block of PUBLIC material (keys + a test signature from each) to hand over so
  the updaters can be switched to the new keys. Secret keys never leave
  %USERPROFILE%\.minisign, and nothing here uploads anything.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup-release-signing.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup-release-signing.ps1 -NewKeys
#>
[CmdletBinding()]
param(
    [switch]$NewKeys,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$KeyDir = Join-Path $HOME '.minisign'
$Primary = Join-Path $KeyDir 'outwarp-release.key'
$Backup = Join-Path $KeyDir 'outwarp-release-backup.key'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [X]  $msg" -ForegroundColor Red; exit 1 }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Ensure-Tool($cmd, $wingetId) {
    if (Has $cmd) { Ok "$cmd found"; return }
    if (-not (Has 'winget')) { Fail "winget is missing: install 'App Installer' from the Microsoft Store" }
    Step "Installing $wingetId"
    winget install --id $wingetId --exact --scope user --silent `
        --accept-package-agreements --accept-source-agreements | Out-Host
    if ($LASTEXITCODE -ne 0) {
        # Some packages have no per-user installer; retry machine-wide (UAC prompt).
        winget install --id $wingetId --exact --silent `
            --accept-package-agreements --accept-source-agreements | Out-Host
    }
    Refresh-Path
}

function Ensure-Minisign {
    if (Has 'minisign') { Ok 'minisign found'; return }
    Ensure-Tool 'minisign' 'jedisct1.minisign'
    if (Has 'minisign') { return }
    # Fallback: the official Windows build from the author's GitHub releases.
    Step 'winget has no minisign here; downloading the official release'
    $rel = Invoke-RestMethod 'https://api.github.com/repos/jedisct1/minisign/releases/latest'
    $asset = $rel.assets | Where-Object { $_.name -match 'win64.*\.zip$' } | Select-Object -First 1
    if (-not $asset) { Fail 'no Windows build in the latest minisign release; install it by hand' }
    $dest = Join-Path $env:LOCALAPPDATA 'Programs\minisign'
    $zip = Join-Path $env:TEMP $asset.name
    Invoke-WebRequest $asset.browser_download_url -OutFile $zip
    Expand-Archive $zip -DestinationPath $dest -Force
    $exe = Get-ChildItem $dest -Recurse -Filter 'minisign.exe' | Select-Object -First 1
    if (-not $exe) { Fail "minisign.exe not found in $($asset.name)" }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -notlike "*$($exe.DirectoryName)*") {
        [Environment]::SetEnvironmentVariable('Path', "$userPath;$($exe.DirectoryName)", 'User')
    }
    Refresh-Path
    if (-not (Has 'minisign')) { Fail 'minisign still not on PATH' }
}

# --- 1. Tools ----------------------------------------------------------------
Step 'Checking tools'
Ensure-Tool 'git' 'Git.Git'
Ensure-Tool 'gh' 'GitHub.cli'
# `python` may be the Microsoft Store alias, which prints a hint instead of a version.
$py = if (Has 'python') { (& python --version 2>&1) | Out-String } else { '' }
if ($py -notmatch 'Python 3\.(1[1-9]|[2-9]\d)') {
    Step 'Installing Python.Python.3.12'
    winget install --id Python.Python.3.12 --exact --scope user --silent `
        --accept-package-agreements --accept-source-agreements | Out-Host
    Refresh-Path
} else { Ok 'python found' }
Ensure-Minisign

Step 'Versions'
& git --version
& gh --version | Select-Object -First 1
& python --version
& minisign -v

# --- 2. GitHub login ----------------------------------------------------------
Step 'GitHub CLI login'
& gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Warn 'gh is not logged in; starting the browser login'
    & gh auth login --hostname github.com --git-protocol https --web
    if ($LASTEXITCODE -ne 0) { Fail 'gh auth login failed' }
}
Ok 'gh is logged in'

if (-not $NewKeys) {
    Write-Host ''
    Ok 'Ready. Per release: python scripts\sign_release.py vX.Y.Z, then python scripts\publish_release.py vX.Y.Z'
    if (-not (Test-Path $Primary)) {
        Warn "No signing key at $Primary. Put the key there, or run again with -NewKeys to replace the keys."
    }
    exit 0
}

# --- 3. New keypairs ------------------------------------------------------------
Step 'Generating the release keypairs'
New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null
foreach ($k in @($Primary, $Backup)) {
    if ((Test-Path $k) -and -not $Force) {
        Fail "$k already exists. Refusing to overwrite a signing key (use -Force if you really mean it)."
    }
}

Write-Host ''
Write-Host '  minisign will ask for a password for each key. Use two DIFFERENT strong'
Write-Host '  passwords and store both in your password manager before continuing.'
Write-Host ''
Write-Host '  PRIMARY key (signs every release):' -ForegroundColor Cyan
& minisign -G -f -p (Join-Path $Repo 'outwarp-release.pub') -s $Primary
if ($LASTEXITCODE -ne 0) { Fail 'could not generate the primary key' }
Write-Host '  BACKUP key (kept offline, only for when the primary is lost):' -ForegroundColor Cyan
& minisign -G -f -p (Join-Path $Repo 'outwarp-release-backup.pub') -s $Backup
if ($LASTEXITCODE -ne 0) { Fail 'could not generate the backup key' }

# A signature from each over the exact message the test suite uses, so the
# repository can prove its compiled keys match what real minisign produces.
Step 'Signing the test fixture with each key (asks each password once more)'
$tmp = Join-Path $env:TEMP 'outwarp-key-fixture'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$msg = Join-Path $tmp 'message.txt'
[IO.File]::WriteAllBytes($msg, [Text.Encoding]::ASCII.GetBytes("deadbeef  fake-asset.whl`ncafebabe  other-asset.exe`n"))
$sigs = @{}
foreach ($pair in @(@('primary', $Primary, 'outwarp-release.pub'), @('backup', $Backup, 'outwarp-release-backup.pub'))) {
    $name, $key, $pub = $pair
    $sig = Join-Path $tmp "$name.minisig"
    & minisign -S -s $key -m $msg -x $sig -t 'OutWarp signature round-trip test'
    if ($LASTEXITCODE -ne 0) { Fail "could not sign with the $name key (wrong password?)" }
    & minisign -V -q -p (Join-Path $Repo $pub) -m $msg -x $sig
    if ($LASTEXITCODE -ne 0) { Fail "the $name signature does not verify" }
    $sigs[$name] = Get-Content -Raw $sig
}
Ok 'both keys sign and verify'

Write-Host ''
Write-Host '---------------- BEGIN OUTWARP PUBLIC KEYS (safe to share) ----------------'
Write-Host '# outwarp-release.pub'
Get-Content -Raw (Join-Path $Repo 'outwarp-release.pub') | Write-Host -NoNewline
Write-Host '# outwarp-release-backup.pub'
Get-Content -Raw (Join-Path $Repo 'outwarp-release-backup.pub') | Write-Host -NoNewline
Write-Host '# primary test signature'
$sigs['primary'] | Write-Host -NoNewline
Write-Host '# backup test signature'
$sigs['backup'] | Write-Host -NoNewline
Write-Host '----------------- END OUTWARP PUBLIC KEYS (safe to share) -----------------'
Write-Host ''
Warn 'Now, before anything else:'
Write-Host "   1. Copy $Backup to an offline USB drive (ideally two), check the copy opens,"
Write-Host '      then DELETE it from this disk. It is only needed if the primary is lost.'
Write-Host "   2. Keep a copy of $Primary (it is encrypted with its password) in your"
Write-Host '      password manager as an attachment, next to its password.'
Write-Host '   3. Paste the block above to Claude so the updaters switch to these keys.'
