# scripts/run-frontend.ps1
Set-Location "$PSScriptRoot\..\frontend\app"

if (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    npm install
}

npx expo start