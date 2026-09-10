# OutWarp - Windows install-from-release helper
#
# Convenience script for automated / unattended deployments (Intune,
# Ansible, kiosk imaging, …). It downloads the latest OutWarpSetup-*.exe
# from GitHub Releases and runs it with elevation.
#
# Regular end users do NOT need this script — they should just download
# OutWarpSetup-x.y.z.exe directly from
# https://github.com/fcrespo07/OutWarp/releases/latest and double-click it.
#
# Usage:
#   irm https://raw.githubusercontent.com/fcrespo07/OutWarp/main/scripts/install-from-release.ps1 | iex
#
# Optional environment overrides (read by the .exe as command-line flags):
#   $env:OUTWARP_VERSION       = '0.1.0'         Pin a specific release tag
#   $env:OUTWARP_COMPONENT     = 'server'|'client'|'full'
#   $env:OUTWARP_SILENT        = '1'             Pass /VERYSILENT to the installer
#   $env:OUTWARP_SKIP_CHECKSUM = '1'             Skip SHA256SUMS verification (NOT
#                                                 recommended — see Test-InstallerSha256)
#
# Requires: Windows 10/11, PowerShell 5.1+, Administrator privileges
# (the installer itself re-elevates if you start it without admin).

$ErrorActionPreference = 'Stop'

$REPO            = 'fcrespo07/OutWarp'
$RELEASE_API     = "https://api.github.com/repos/$REPO/releases/latest"
$RELEASE_API_TAG = "https://api.github.com/repos/$REPO/releases/tags/{0}"
$ASSET_PATTERN   = 'OutWarpSetup-*.exe'

function Write-Info { param([string]$Msg) Write-Host "==> $Msg" -ForegroundColor Cyan }
function Write-OK   { param([string]$Msg) Write-Host "  [OK] $Msg" -ForegroundColor Green }
function Write-Fail {
    param([string]$Msg)
    Write-Host "  [X]  $Msg" -ForegroundColor Red
    Read-Host "  Press Enter to exit"
    exit 1
}

function Show-Banner {
    $art = @'

    ____        __  _       __
   / __ \__  __/ /_| |     / /___ __________
  / / / / / / / __/| | /| / / __ `/ ___/ __ \
 / /_/ / /_/ / /_  | |/ |/ / /_/ / /  / /_/ /
 \____/\__,_/\__/  |__/|__/\__,_/_/  / .___/
                                    /_/

'@
    Write-Host $art -ForegroundColor Cyan
    Write-Host "  WireGuard over WebSocket - Windows bootstrap" -ForegroundColor DarkGray
    Write-Host ""
}

function Get-ReleaseAsset {
    $version = $env:OUTWARP_VERSION
    if ($version) {
        $url = [string]::Format($RELEASE_API_TAG, $version)
        Write-Info "Fetching release metadata for tag $version"
    } else {
        $url = $RELEASE_API
        Write-Info "Fetching latest release metadata"
    }

    $headers = @{ 'User-Agent' = 'OutWarp-Installer' }
    try {
        $release = Invoke-RestMethod -Uri $url -Headers $headers -UseBasicParsing
    } catch {
        Write-Fail "Failed to query GitHub Releases: $($_.Exception.Message)"
    }

    $asset = $release.assets | Where-Object { $_.name -like $ASSET_PATTERN } | Select-Object -First 1
    if (-not $asset) {
        Write-Fail "No asset matching '$ASSET_PATTERN' in release $($release.tag_name)."
    }
    $sumsAsset = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS.txt' } | Select-Object -First 1
    Write-OK "Release: $($release.tag_name) — asset $($asset.name)"
    return [PSCustomObject]@{ Installer = $asset; Sums = $sumsAsset }
}

function Download-Installer {
    param([Parameter(Mandatory)]$Asset)
    $dest = Join-Path $env:TEMP $Asset.name
    Write-Info "Downloading $($Asset.name) (~$([math]::Round($Asset.size / 1MB, 1)) MB)"
    Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $dest -UseBasicParsing
    Write-OK "Saved to $dest"
    return $dest
}

# Verify the downloaded installer's SHA256 against the release's SHA256SUMS.txt
# before it ever runs with elevation. Mirrors installer/linux/install.sh's
# _verify_wheel_sha256 (FIX-12) — this script was the one place OutWarp shipped
# that downloaded and ran an elevated binary with no integrity check at all:
# a compromised/MITM'd download would run silently, unattended, as SYSTEM-
# adjacent Administrator, which is exactly the deployment (Intune, Ansible,
# kiosk imaging) where nobody is watching to notice something's wrong.
#   - no SHA256SUMS.txt asset → legacy release; skip with a warning
#   - fetch/parse failure     → refuse (could be a MITM dropping the manifest)
#   - name not listed         → refuse (wrong release or tampered manifest)
#   - hash mismatch           → refuse
function Test-InstallerSha256 {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Name,
        $SumsAsset
    )

    if ($env:OUTWARP_SKIP_CHECKSUM -eq '1') {
        Write-Host "  [!] OUTWARP_SKIP_CHECKSUM=1 - skipping integrity check (NOT recommended)" -ForegroundColor Yellow
        return
    }
    if (-not $SumsAsset) {
        Write-Host "  [!] Release has no SHA256SUMS.txt asset (legacy release) - integrity check skipped" -ForegroundColor Yellow
        return
    }

    Write-Info "Verifying SHA256 against $($SumsAsset.name)"
    $sumsPath = Join-Path $env:TEMP $SumsAsset.name
    try {
        Invoke-WebRequest -Uri $SumsAsset.browser_download_url -OutFile $sumsPath -UseBasicParsing
    } catch {
        Write-Fail "Could not fetch SHA256SUMS.txt: $($_.Exception.Message)`n`n  A network failure here is not the same as 'no manifest available' - refusing to install. Re-run when the connection is stable, or set OUTWARP_SKIP_CHECKSUM=1 only if you understand the risk."
    }

    # sha256sum format: "<64-hex-digest>  <filename>" (two spaces).
    $expected = $null
    foreach ($line in Get-Content $sumsPath) {
        if ($line -match "^([0-9a-fA-F]{64})\s+\*?$([regex]::Escape($Name))$") {
            $expected = $Matches[1].ToLower()
            break
        }
    }
    Remove-Item $sumsPath -ErrorAction SilentlyContinue
    if (-not $expected) {
        Write-Fail "'$Name' is not listed in SHA256SUMS.txt - aborting (wrong release or tampered manifest)"
    }

    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Write-Fail "SHA256 mismatch for ${Name}:`n  expected: $expected`n  actual:   $actual"
    }
    Write-OK "Integrity verified (SHA256: $($actual.Substring(0, 16))...)"
}

function Invoke-Installer {
    param([Parameter(Mandatory)][string]$Path)

    $args = @()
    if ($env:OUTWARP_SILENT -eq '1') {
        $args += '/VERYSILENT'
        $args += '/SUPPRESSMSGBOXES'
    }
    if ($env:OUTWARP_COMPONENT) {
        switch ($env:OUTWARP_COMPONENT.ToLower()) {
            'client' { $args += '/TYPE=client';  $args += '/COMPONENTS=client,wstunnel,wireguard' }
            'server' { $args += '/TYPE=server';  $args += '/COMPONENTS=server\gui,server\cli,wstunnel,wireguard' }
            'full'   { $args += '/TYPE=full'; }
            default  { Write-Host "  [!] Unknown OUTWARP_COMPONENT=$($env:OUTWARP_COMPONENT) — ignoring" -ForegroundColor Yellow }
        }
    }

    Write-Info "Launching installer: $Path $($args -join ' ')"
    # Start-Process re-prompts UAC on its own — the user gets the standard
    # Windows consent dialog, exactly like double-clicking the .exe.
    $proc = Start-Process -FilePath $Path -ArgumentList $args -Verb runAs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
        Write-Fail "Installer exited with code $($proc.ExitCode). See setup log under %TEMP%\\Setup Log*.txt"
    }
    Write-OK "Installer finished"
}

function Main {
    Show-Banner
    $found   = Get-ReleaseAsset
    $exePath = Download-Installer -Asset $found.Installer
    Test-InstallerSha256 -Path $exePath -Name $found.Installer.name -SumsAsset $found.Sums
    Invoke-Installer -Path $exePath
    Write-Host ""
    Write-OK "All done. Open OutWarp from the Start menu or your desktop."
}

try {
    Main
} catch {
    Write-Host ""
    Write-Host "  [X]  Unexpected error: $_" -ForegroundColor Red
    Read-Host "  Press Enter to exit"
    exit 1
}
