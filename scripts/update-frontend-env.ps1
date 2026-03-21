# scripts/update-frontend-env.ps1
# Detects a good LAN IPv4 (prefers Wi-Fi/Ethernet), then writes it to frontend/app/.env

$ErrorActionPreference = "Stop"

$frontendEnvPath = Join-Path $PSScriptRoot "..\frontend\app\.env"
$port = 8000

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

# Fallback: any Preferred address that looks like private LAN (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
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
$serverUrl = "http://$ip`:$port"

# Ensure target directory exists
$dir = Split-Path $frontendEnvPath -Parent
if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

# Write .env (overwrite)
$envContent = @"
EXPO_PUBLIC_SERVER_URL=$serverUrl
"@

Set-Content -Path $frontendEnvPath -Value $envContent -Encoding ascii

Write-Host "Wrote $frontendEnvPath" -ForegroundColor Green
Write-Host "EXPO_PUBLIC_SERVER_URL=$serverUrl"
