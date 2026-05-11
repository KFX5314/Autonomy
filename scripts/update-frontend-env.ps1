# scripts/update-frontend-env.ps1
# Detects the best IP for the frontend to reach the backend.
# Prefers Tailscale IP (works across networks), falls back to LAN IP.

$ErrorActionPreference = "Stop"

$frontendEnvPath = Join-Path $PSScriptRoot "..\frontend\app\.env"
$port = 8000

# ─── 1. Try Tailscale IP first (works from any network) ───────────
$ip = $null
$tsIp = tailscale ip -4 2>$null
if ($tsIp) {
  $ip = $tsIp.Trim()
  Write-Host "Using Tailscale IP: $ip" -ForegroundColor Cyan
}

# ─── 2. Fallback to LAN IP ────────────────────────────────────────
if (-not $ip) {
  Write-Host "No Tailscale IP found, falling back to LAN IP" -ForegroundColor Yellow

  # Pull IPv4 addresses excluding loopback + APIPA
  $ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
      $_.IPAddress -notlike "127.*" -and
      $_.IPAddress -notlike "169.254.*"
    } |
    Select-Object InterfaceAlias, IPAddress, PrefixOrigin, AddressState

  # Prefer Wi-Fi / Ethernet first (avoid VPN adapters like NordLynx/OpenVPN)
  $preferred = $ips | Where-Object {
    $_.AddressState -eq "Preferred" -and
    ($_.InterfaceAlias -match "Wi-?Fi|Wireless|Ethernet")
  } | Select-Object -First 1

  # Fallback: any Preferred address that looks like private LAN
  if (-not $preferred) {
    $preferred = $ips | Where-Object {
      $_.AddressState -eq "Preferred" -and
      (
        $_.IPAddress -match '^192\.168\.' -or
        $_.IPAddress -match '^10\.' -or
        $_.IPAddress -match '^172\.(1[6-9]|2[0-9]|3[0-1])\.'
      )
    } | Select-Object -First 1
  }

  if (-not $preferred) {
    throw "No suitable IPv4 address found."
  }
  $ip = $preferred.IPAddress
}
$serverUrl = "http://$ip`:$port"

# Ensure target directory exists
$dir = Split-Path $frontendEnvPath -Parent
if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

# Write/update server URL while preserving any optional frontend tuning values.
$existingLines = @()
if (Test-Path $frontendEnvPath) {
  $existingLines = Get-Content -Path $frontendEnvPath |
    Where-Object { $_ -notmatch '^\s*EXPO_PUBLIC_SERVER_URL\s*=' }
}

$envContent = @("EXPO_PUBLIC_SERVER_URL=$serverUrl") + $existingLines
Set-Content -Path $frontendEnvPath -Value $envContent -Encoding ascii

Write-Host "Wrote $frontendEnvPath" -ForegroundColor Green
Write-Host "EXPO_PUBLIC_SERVER_URL=$serverUrl"
