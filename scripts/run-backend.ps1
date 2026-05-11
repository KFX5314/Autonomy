# scripts/run-backend.ps1
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

function Get-OllamaTags {
    param([string]$TagsUrl)

    try {
        return Invoke-RestMethod -Uri $TagsUrl -Method GET -TimeoutSec 2
    } catch {
        return $null
    }
}

function Start-OllamaServer {
    $ollamaCommand = Get-Command "ollama" -ErrorAction SilentlyContinue
    if (-not $ollamaCommand) {
        Write-Host "  Ollama CLI not found. Install Ollama or add it to PATH." -ForegroundColor Red
        exit 1
    }

    Write-Host "  Starting Ollama server with: ollama serve" -ForegroundColor Yellow
    try {
        Start-Process -FilePath $ollamaCommand.Source -ArgumentList "serve" -WindowStyle Hidden | Out-Null
    } catch {
        Write-Host "  Failed to launch Ollama: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# 1. Kill old uvicorn / python processes on port 8000
Write-Host "`n=== Cleaning up old processes ===" -ForegroundColor Cyan
$oldPids = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
if ($oldPids) {
    foreach ($p in $oldPids) {
        $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  Killing $($proc.ProcessName) (PID $p) on port 8000" -ForegroundColor Yellow
            Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 1
    Write-Host "  Port 8000 freed." -ForegroundColor Green
} else {
    Write-Host "  Port 8000 is free." -ForegroundColor Green
}

# 2. Ensure MariaDB service is running
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

# 3. Ensure Ollama API is running, not just the ollama.exe process
Write-Host "`n=== Checking Ollama ===" -ForegroundColor Cyan
$ollamaUrl = if ($env:OLLAMA_URL) { $env:OLLAMA_URL } else { "http://127.0.0.1:11434" }
$ollamaBaseUrl = $ollamaUrl.TrimEnd("/")
$ollamaTagsUrl = "$ollamaBaseUrl/api/tags"
$ollamaProc = Get-Process -Name "ollama" -ErrorAction SilentlyContinue

if ($ollamaProc) {
    Write-Host "  Ollama process found. Verifying API at $ollamaBaseUrl..." -ForegroundColor Gray
} else {
    Write-Host "  Ollama process not found." -ForegroundColor Yellow
}

$ollamaTags = Get-OllamaTags -TagsUrl $ollamaTagsUrl
if (-not $ollamaTags) {
    Write-Host "  Ollama API is not responding. Launching server..." -ForegroundColor Yellow
    Start-OllamaServer
}

Write-Host "  Waiting for Ollama API..." -ForegroundColor Gray
for ($i = 0; $i -lt 30; $i++) {
    $ollamaTags = Get-OllamaTags -TagsUrl $ollamaTagsUrl
    if ($ollamaTags) {
        break
    }

    Start-Sleep -Seconds 1
}

if ($ollamaTags) {
    Write-Host "  Ollama API ready." -ForegroundColor Green
} else {
    Write-Host "  Ollama API still is not responding at $ollamaBaseUrl." -ForegroundColor Red
    Write-Host "  Run 'ollama serve' manually to see the underlying error." -ForegroundColor Yellow
    exit 1
}

# Verify the configured LLM model is pulled locally
$llmModel = if ($env:LLM_MODEL) { $env:LLM_MODEL } else { "mistral:7b-instruct" }
Write-Host "  Checking model '$llmModel'..." -ForegroundColor Gray
if ($ollamaTags.models.name -contains $llmModel) {
    Write-Host "  Model '$llmModel' OK" -ForegroundColor Green
} else {
    Write-Host "  Model '$llmModel' not found locally. Pull it with:" -ForegroundColor Red
    Write-Host "    ollama pull $llmModel" -ForegroundColor Yellow
    exit 1
}

# 4. Activate venv and set environment
Write-Host "`n=== Starting backend ===" -ForegroundColor Cyan
.\.venv\Scripts\Activate.ps1
Set-Location backend

if (-not $env:DB_USER) { $env:DB_USER = "tfg_app" }
if (-not $env:DB_PASSWORD) { $env:DB_PASSWORD = "tfg_pass_2024" }
if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "ollama" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "mistral:7b-instruct" }
if (-not $env:STT_DEVICE) { $env:STT_DEVICE = "cuda" }
if (-not $env:SPEAKER_DEVICE) { $env:SPEAKER_DEVICE = "cpu" }

python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
