# scripts/run-frontend.ps1
Set-Location "$PSScriptRoot\..\frontend\app"

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    npm install
}

# Use Tailscale IP if available, otherwise fall back to tunnel
$tsIp = tailscale ip -4 2>$null
if ($tsIp) {
    Write-Host "Using Tailscale IP: $tsIp" -ForegroundColor Cyan
    $env:REACT_NATIVE_PACKAGER_HOSTNAME = $tsIp
    npx expo start --host lan
} else {
    Write-Host "No Tailscale IP found, falling back to --tunnel" -ForegroundColor Yellow
    npx expo start --tunnel
}