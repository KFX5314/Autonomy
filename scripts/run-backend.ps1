# scripts/run-backend.ps1
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

# ─── 1. Kill old uvicorn / python processes on port 8000 ──────────
Write-Host "`n=== Cleaning up old processes ===" -ForegroundColor Cyan
$oldPids = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
if ($oldPids) {
    foreach ($pid in $oldPids) {
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Killing $($proc.ProcessName) (PID $pid) on port 8000" -ForegroundColor Yellow
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
    Write-Host "  Port 8000 freed." -ForegroundColor Green
} else {
    Write-Host "  Port 8000 is free." -ForegroundColor Green
}

# ─── 2. Ensure MariaDB service is running ─────────────────────────
Write-Host "`n=== Checking MariaDB ===" -ForegroundColor Cyan
$mariaService = Get-Service -Name "MariaDB" -ErrorAction SilentlyContinue
if (-not $mariaService) {
    Write-Host "  MariaDB service not found! Install MariaDB first." -ForegroundColor Red
    exit 1
}
if ($mariaService.Status -ne "Running") {
    Write-Host "  MariaDB is stopped. Starting..." -ForegroundColor Yellow
    Start-Service -Name "MariaDB"
    Start-Sleep -Seconds 2
    $mariaService = Get-Service -Name "MariaDB"
    if ($mariaService.Status -eq "Running") {
        Write-Host "  MariaDB started." -ForegroundColor Green
    } else {
        Write-Host "  Failed to start MariaDB (status: $($mariaService.Status))." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  MariaDB is running." -ForegroundColor Green
}

# ─── 3. Ensure Ollama is running ──────────────────────────────────
Write-Host "`n=== Checking Ollama ===" -ForegroundColor Cyan
$ollamaProc = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaProc) {
    Write-Host "  Ollama is not running. Starting..." -ForegroundColor Yellow
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    $ollamaProc = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
    if ($ollamaProc) {
        Write-Host "  Ollama started." -ForegroundColor Green
    } else {
        Write-Host "  Failed to start Ollama. Is it installed?" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "  Ollama is running." -ForegroundColor Green
}

# Verify Ollama API is responsive
Write-Host "  Waiting for Ollama API..." -ForegroundColor Gray
$ollamaReady = $false
for ($i = 0; $i -lt 10; $i++) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method GET -TimeoutSec 2
        $ollamaReady = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if ($ollamaReady) {
    Write-Host "  Ollama API ready." -ForegroundColor Green
} else {
    Write-Host "  WARNING: Ollama API not responding. Backend may fail LLM calls." -ForegroundColor Yellow
}

# ─── 4. Activate venv and set environment ─────────────────────────
Write-Host "`n=== Starting backend ===" -ForegroundColor Cyan
.\.venv\Scripts\Activate.ps1
Set-Location backend

if (-not $env:DB_USER) { $env:DB_USER = "tfg_app" }
if (-not $env:DB_PASSWORD) { $env:DB_PASSWORD = "tfg_pass_2024" }
if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "ollama" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "phi3:mini" }
if (-not $env:STT_DEVICE) { $env:STT_DEVICE = "cuda" }

python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
