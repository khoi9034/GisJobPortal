$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvPath = Join-Path $RepoRoot "backend\.env"

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
  }
}

function Set-EnvLine([string[]]$Lines, [string]$Name, [string]$Value) {
  $Pattern = "^$([regex]::Escape($Name))="
  $Line = "$Name=$Value"
  if ($Lines | Where-Object { $_ -match $Pattern }) {
    return $Lines | ForEach-Object { if ($_ -match $Pattern) { $Line } else { $_ } }
  }
  @($Lines + $Line)
}

if (-not (Test-Path $EnvPath)) {
  New-Item -ItemType Directory -Force -Path (Split-Path $EnvPath) | Out-Null
  Set-Content -Path $EnvPath -Encoding utf8 -Value @(
    "DATABASE_URL=sqlite:///./data/jobs.sqlite3",
    "API_ENV=local",
    "CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app"
  )
}

$Lines = @(Get-Content $EnvPath -ErrorAction SilentlyContinue)
$ClientId = Convert-ToPlainText (Read-Host "Paste Gmail OAuth client ID" -AsSecureString)
$ClientSecret = Convert-ToPlainText (Read-Host "Paste Gmail OAuth client secret" -AsSecureString)

if ([string]::IsNullOrWhiteSpace($ClientId) -or [string]::IsNullOrWhiteSpace($ClientSecret)) {
  throw "GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are required."
}

$Lines = Set-EnvLine $Lines "GMAIL_INGESTION_ENABLED" "true"
$Lines = Set-EnvLine $Lines "GMAIL_CLIENT_ID" $ClientId
$Lines = Set-EnvLine $Lines "GMAIL_CLIENT_SECRET" $ClientSecret
$Lines = Set-EnvLine $Lines "GMAIL_TOKEN_PATH" "runtime/secrets/gmail_token.local.json"
$Lines = Set-EnvLine $Lines "GMAIL_ALERT_QUERY" '(from:linkedin.com OR from:indeed.com OR subject:("job alert") OR subject:(GIS) OR subject:(geospatial)) newer_than:14d'
Set-Content -Path $EnvPath -Encoding utf8 -Value $Lines

Write-Host "Gmail local env saved to ignored backend/.env."
Write-Host "Next: python scripts\setup_gmail_oauth.py"
