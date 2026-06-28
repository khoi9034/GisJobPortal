$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$BackendUrl = "http://127.0.0.1:8001"
$FrontendUrl = "http://localhost:3000"
$BackendEnv = Join-Path $RepoRoot "backend\.env"
$FrontendEnv = Join-Path $RepoRoot "frontend\.env.local"
$LogDir = Join-Path $RepoRoot "runtime\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "Repo: $RepoRoot"
Write-Host "backend/.env: $(if (Test-Path $BackendEnv) { 'found' } else { 'missing' })"

if (-not (Test-Path $FrontendEnv)) {
  @"
NEXT_PUBLIC_API_MODE=local
NEXT_PUBLIC_API_BASE_URL=$BackendUrl
"@ | Set-Content -Path $FrontendEnv -Encoding utf8
  Write-Host "Created ignored frontend/.env.local for local backend mode."
} else {
  Write-Host "frontend/.env.local: found"
}

function Test-Url($Url) {
  try {
    Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

if (Test-Url "$BackendUrl/health") {
  Write-Host "Backend already running: $BackendUrl"
} else {
  $BackendOut = Join-Path $LogDir "backend_8001.out.log"
  $BackendErr = Join-Path $LogDir "backend_8001.err.log"
  $Backend = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "backend.app.api:app", "--host", "127.0.0.1", "--port", "8001", "--reload") -WorkingDirectory $RepoRoot -RedirectStandardOutput $BackendOut -RedirectStandardError $BackendErr -WindowStyle Hidden -PassThru
  Write-Host "Started backend PID $($Backend.Id). Logs: $BackendOut"
}

if (Test-Url $FrontendUrl) {
  Write-Host "Frontend already running: $FrontendUrl"
} else {
  $FrontendOut = Join-Path $LogDir "frontend_3000.out.log"
  $FrontendErr = Join-Path $LogDir "frontend_3000.err.log"
  $Frontend = Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev", "--", "--hostname", "localhost", "--port", "3000") -WorkingDirectory (Join-Path $RepoRoot "frontend") -RedirectStandardOutput $FrontendOut -RedirectStandardError $FrontendErr -WindowStyle Hidden -PassThru
  Write-Host "Started frontend PID $($Frontend.Id). Logs: $FrontendOut"
}

Write-Host "Backend:  $BackendUrl"
Write-Host "Frontend: $FrontendUrl"
Write-Host "Run python scripts\check_ports.py if the dashboard still shows demo data."
