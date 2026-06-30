$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ServiceId = "srv-d90stu3sq97s739mpta0"
$BackendUrl = "https://gisjobportal.onrender.com"
$RenderApiBase = "https://api.render.com/v1"
$EnvPath = Join-Path $RepoRoot "backend\.env"
$TokenPath = Join-Path $RepoRoot "runtime\secrets\gmail_token.local.json"

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
  }
}

function Read-LocalEnv {
  $Rows = @{}
  if (Test-Path $EnvPath) {
    Get-Content $EnvPath | ForEach-Object {
      if ($_ -match "^\s*([^#][^=]+)=(.*)$") {
        $Rows[$Matches[1].Trim()] = $Matches[2].Trim().Trim('"').Trim("'")
      }
    }
  }
  $Rows
}

function Invoke-RenderApi($Method, $Path, $Body = $null) {
  $Headers = @{ Authorization = "Bearer $ApiKey"; Accept = "application/json" }
  $Params = @{ Method = $Method; Uri = "$RenderApiBase$Path"; Headers = $Headers; TimeoutSec = 45 }
  if ($null -ne $Body) {
    $Params.ContentType = "application/json"
    $Params.Body = ($Body | ConvertTo-Json -Depth 5)
  }
  Invoke-RestMethod @Params
}

function Set-RenderEnv($Name, $Value) {
  try {
    Invoke-RenderApi "Put" "/services/$ServiceId/env-vars/$([uri]::EscapeDataString($Name))" @{ value = $Value } | Out-Null
  } catch {
    Invoke-RenderApi "Post" "/services/$ServiceId/env-vars" @{ key = $Name; value = $Value } | Out-Null
  }
  Write-Host "- ${Name}: updated"
}

$ApiKey = $env:RENDER_API_KEY
if ([string]::IsNullOrWhiteSpace($ApiKey)) {
  $ApiKey = Convert-ToPlainText (Read-Host "Paste Render API key, then press Enter" -AsSecureString)
}

$Env = Read-LocalEnv
$ClientId = $Env["GMAIL_CLIENT_ID"]
$ClientSecret = $Env["GMAIL_CLIENT_SECRET"]
if ([string]::IsNullOrWhiteSpace($ClientId) -or [string]::IsNullOrWhiteSpace($ClientSecret)) {
  throw "GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are missing from backend/.env. Run .\scripts\setup_gmail_local_env.ps1 first."
}
if (-not (Test-Path $TokenPath)) {
  throw "Gmail token missing at runtime\secrets\gmail_token.local.json. Run python scripts\setup_gmail_oauth.py first."
}

$TokenBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($TokenPath))
$Query = '(from:linkedin.com OR from:indeed.com OR subject:("job alert") OR subject:(GIS) OR subject:(geospatial)) newer_than:14d'

try {
  Write-Host "Syncing Gmail env vars to Render service $ServiceId..."
  Set-RenderEnv "GMAIL_INGESTION_ENABLED" "true"
  Set-RenderEnv "GMAIL_CLIENT_ID" $ClientId
  Set-RenderEnv "GMAIL_CLIENT_SECRET" $ClientSecret
  Set-RenderEnv "GMAIL_TOKEN_JSON_BASE64" $TokenBase64
  Set-RenderEnv "GMAIL_ALERT_QUERY" $Query

  Write-Host "Triggering Render deploy..."
  Invoke-RenderApi "Post" "/services/$ServiceId/deploys" | Out-Null

  for ($i = 1; $i -le 30; $i++) {
    try {
      $Health = Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 25
      $Status = Invoke-RestMethod -Uri "$BackendUrl/deployment/status" -TimeoutSec 25
      Write-Host "poll ${i}: health=$($Health.status) api_env=$($Status.api_env) db=$($Status.database_runtime_type)"
      if ($Health.status -eq "ok" -and $Status.api_env -eq "production") { break }
    } catch {
      Write-Host "poll ${i}: Render may be deploying"
    }
    Start-Sleep -Seconds 20
  }
  Write-Host "Gmail env sync complete. No secret values were printed."
} finally {
  $ApiKey = $null
}
