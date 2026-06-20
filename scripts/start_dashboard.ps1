# Start QuantAI dashboard (API + built SPA) on http://localhost:8080
Set-Location $PSScriptRoot\..

if (-not (Test-Path "frontend\dist\index.html")) {
    Write-Host "Building frontend..."
    Push-Location frontend
    npm run build
    Pop-Location
}

Write-Host "Starting dashboard at http://localhost:8080"
python -c "from src.web.dashboard import run_dashboard; run_dashboard(host='127.0.0.1', port=8080)"
