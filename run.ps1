$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$port = if ($env:PORT) { $env:PORT } else { "8124" }

Write-Host "Lecture Notes Agent" -ForegroundColor Cyan
Write-Host "Starting http://127.0.0.1:$port ..." -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray

python -m uvicorn backend.main:app --host 127.0.0.1 --port $port
