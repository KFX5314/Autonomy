# scripts/run-frontend.ps1
param(
    [switch]$Tunnel
)

$ErrorActionPreference = "Stop"

$appDir = Join-Path $PSScriptRoot "..\frontend\app"
$frontendEnvPath = Join-Path $appDir ".env"
$port = 8000

function Get-TailscaleIPv4 {
    if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
        return $null
    }

    try {
        $raw = & tailscale ip -4 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $null
        }
        $ip = $raw |
            Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' } |
            Select-Object -First 1
        if ($ip) {
            return $ip.Trim()
        }
    } catch {
        return $null
    }

    return $null
}

function Get-LanIPv4 {
    $ignoredAdapters = "Loopback|vEthernet|Virtual|VMware|VirtualBox|Tailscale|ZeroTier|Nord|OpenVPN|WireGuard|VPN|Bluetooth"
    $privatePattern = '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)'

    try {
        $ips = Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.InterfaceAlias -notmatch $ignoredAdapters
            } |
            Select-Object InterfaceAlias, IPAddress, PrefixOrigin, AddressState
    } catch {
        $ips = @()
    }

    if (-not $ips) {
        $rawIpconfig = ipconfig
        $candidates = @()
        $currentAdapter = ""
        foreach ($line in $rawIpconfig) {
            $trimmed = $line.Trim()
            if ($trimmed -match '^(.*Adaptador.*|.*adapter.*):$') {
                $currentAdapter = $trimmed.TrimEnd(":")
                continue
            }
            $match = [regex]::Match($line, 'IPv4[^:]*:\s*(\d{1,3}(?:\.\d{1,3}){3})')
            if (-not $match.Success -or -not $currentAdapter -or $currentAdapter -match $ignoredAdapters) {
                continue
            }
            $candidate = $match.Groups[1].Value
            if ($candidate -match $privatePattern -and $candidate -notlike "169.254.*") {
                $candidates += [pscustomobject]@{
                    InterfaceAlias = $currentAdapter
                    IPAddress = $candidate
                    PrefixOrigin = ""
                    AddressState = "Preferred"
                }
            }
        }
        $preferredIpconfig = $candidates | Where-Object {
            $_.InterfaceAlias -match "Wi-?Fi|Wireless|Ethernet"
        } | Select-Object -First 1
        if (-not $preferredIpconfig) {
            $preferredIpconfig = $candidates | Select-Object -First 1
        }
        if ($preferredIpconfig) {
            return $preferredIpconfig
        }
    }

    $preferred = $ips | Where-Object {
        $_.AddressState -eq "Preferred" -and
        $_.IPAddress -match $privatePattern -and
        ($_.InterfaceAlias -match "Wi-?Fi|Wireless|Ethernet")
    } | Select-Object -First 1

    if (-not $preferred) {
        $preferred = $ips | Where-Object {
            $_.AddressState -eq "Preferred" -and
            $_.IPAddress -match $privatePattern
        } | Select-Object -First 1
    }

    if (-not $preferred) {
        throw "No suitable LAN IPv4 address found. Connect to Wi-Fi/Ethernet or run '.\scripts\run-frontend.ps1 -Tunnel'."
    }

    return $preferred
}

function Update-FrontendEnv {
    param(
        [Parameter(Mandatory = $true)][string]$ServerUrl
    )

    $existingLines = @()
    if (Test-Path $frontendEnvPath) {
        $existingLines = Get-Content -Path $frontendEnvPath |
            Where-Object { $_ -notmatch '^\s*EXPO_PUBLIC_SERVER_URL\s*=' }
    }

    $envContent = @("EXPO_PUBLIC_SERVER_URL=$ServerUrl") + $existingLines
    Set-Content -Path $frontendEnvPath -Value $envContent -Encoding ascii
}

Set-Location $appDir

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    npm install
}

if ($Tunnel) {
    Write-Host "Starting Expo with tunnel mode by request." -ForegroundColor Yellow
    npx expo start --tunnel
    exit $LASTEXITCODE
}

$ip = Get-TailscaleIPv4
if ($ip) {
    Write-Host "Using Tailscale IP: $ip" -ForegroundColor Cyan
} else {
    $lan = Get-LanIPv4
    $ip = $lan.IPAddress
    Write-Host "No active Tailscale IP found; using LAN IP: $ip ($($lan.InterfaceAlias))" -ForegroundColor Yellow
}

$serverUrl = "http://$ip`:$port"
Update-FrontendEnv -ServerUrl $serverUrl
Write-Host "EXPO_PUBLIC_SERVER_URL=$serverUrl" -ForegroundColor Green

$env:REACT_NATIVE_PACKAGER_HOSTNAME = $ip
npx expo start --host lan
