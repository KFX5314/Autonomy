# scripts/run-backend-e2e.ps1
# Test-only backend launcher used by backend/tests/test_memory_server_e2e_optional.py.
# It intentionally avoids touching the normal development launcher.

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

# Free the test port.
Write-Host "`n=== E2E backend: cleaning up old processes ===" -ForegroundColor Cyan
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
}

Write-Host "`n=== E2E backend: checking MariaDB ===" -ForegroundColor Cyan
$mariaService = Get-Service -Name "MariaDB" -ErrorAction SilentlyContinue
if (-not $mariaService) {
    Write-Host "  MariaDB service not found." -ForegroundColor Red
    exit 1
}
if ($mariaService.Status -ne "Running") {
    Write-Host "  MariaDB is stopped. Starting..." -ForegroundColor Yellow
    Start-Service -Name "MariaDB"
    Start-Sleep -Seconds 2
}

Write-Host "`n=== E2E backend: starting FastAPI without model warmup ===" -ForegroundColor Cyan

# The memory e2e test only exercises auth/patient/memory endpoints. Avoid
# requiring Ollama, Whisper or SpeechBrain startup for that narrow check.
$env:TFG_SKIP_MODEL_WARMUP = "1"
$env:TFG_SKIP_HEALTH_LLM = "1"

if (-not $env:DB_HOST) { $env:DB_HOST = "127.0.0.1" }
if (-not $env:DB_PORT) { $env:DB_PORT = "3306" }
if (-not $env:DB_NAME) { $env:DB_NAME = "tfg_demencia_test" }
if (-not $env:DB_USER) { $env:DB_USER = "tfg_app" }
if (-not $env:DB_PASSWORD) { $env:DB_PASSWORD = "tfg_pass_2024" }
if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "ollama" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "mistral:7b-instruct" }
if (-not $env:STT_DEVICE) { $env:STT_DEVICE = "cuda" }
if (-not $env:SPEAKER_DEVICE) { $env:SPEAKER_DEVICE = "cpu" }

$pythonCommand = "python"
$venvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$venvActivate = Join-Path (Get-Location) ".venv\Scripts\Activate.ps1"
if (Test-Path $venvPython) {
    $venvOk = $false
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $venvPython --version *> $null
        $venvOk = ($LASTEXITCODE -eq 0)
    } catch {
        $venvOk = $false
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($venvOk) {
        . $venvActivate
        Write-Host "  Using project virtual environment." -ForegroundColor Green
    } else {
        Write-Host "  Project .venv is not runnable. Falling back to PATH python." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Project .venv not found. Falling back to PATH python." -ForegroundColor Yellow
}

Set-Location backend
& $pythonCommand -m uvicorn src.server:app --host 0.0.0.0 --port 8000
