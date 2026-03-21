# scripts/run-backend.ps1
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

.\.venv\Scripts\Activate.ps1
Set-Location backend

# Set defaults if not already set
if (-not $env:DB_USER) { $env:DB_USER = "tfg_app" }
if (-not $env:DB_PASSWORD) { $env:DB_PASSWORD = "tfg_pass_2024" }
if (-not $env:LLM_PROVIDER) { $env:LLM_PROVIDER = "ollama" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "phi3:mini" }
if (-not $env:STT_DEVICE) { $env:STT_DEVICE = "cuda" }

python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
