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
#   $env:OUTWARP_VERSION    = '0.1.0'         Pin a specific release tag
#   $env:OUTWARP_COMPONENT  = 'server'|'client'|'full'
#   $env:OUTWARP_SILENT     = '1'             Pass /VERYSILENT to the installer
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
    Write-OK "Release: $($release.tag_name) — asset $($asset.name)"
    return $asset
}

function Download-Installer {
    param([Parameter(Mandatory)]$Asset)
    $dest = Join-Path $env:TEMP $Asset.name
    Write-Info "Downloading $($Asset.name) (~$([math]::Round($Asset.size / 1MB, 1)) MB)"
    Invoke-WebRequest -Uri $Asset.browser_download_url -OutFile $dest -UseBasicParsing
    Write-OK "Saved to $dest"
    return $dest
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
    $asset   = Get-ReleaseAsset
    $exePath = Download-Installer -Asset $asset
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
