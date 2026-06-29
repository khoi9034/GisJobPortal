$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$ServiceId = "srv-d90stu3sq97s739mpta0"
$BackendUrl = "https://gisjobportal.onrender.com"
$LiveSite = "https://gis-job-portal.vercel.app"
$RenderApiBase = "https://api.render.com/v1"
$AdminTokenPath = Join-Path $RepoRoot "runtime\secrets\admin_refresh_token.local.txt"
$RequiredEnvVars = @(
  "DATABASE_URL",
  "API_ENV",
  "CORS_ORIGINS",
  "USAJOBS_USER_AGENT",
  "USAJOBS_AUTHORIZATION_KEY",
  "ADMIN_REFRESH_TOKEN"
)

trap {
  Clear-Secrets
  Write-Host ""
  Write-Host "Hosted refresh setup failed: $($_.Exception.Message)"
  Write-Host "No Render API key was saved."
  $null = Read-Host "Press Enter to close"
  exit 1
}

function Clear-Secrets {
  $script:RenderApiKey = $null
  $script:SecureKey = $null
  $script:AdminToken = $null
}

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
  }
}

function New-AdminToken {
  $Bytes = [byte[]]::new(48)
  [Security.Cryptography.RandomNumberGenerator]::Fill($Bytes)
  [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Redact-Secrets([string]$Text) {
  $Value = "$Text"
  foreach ($Secret in @($script:RenderApiKey, $script:AdminToken)) {
    if ($Secret -and $Secret.Length -gt 4) {
      $Value = $Value.Replace($Secret, "[redacted]")
    }
  }
  $Value
}

function Get-SafeErrorBody($ErrorRecord) {
  $Response = $ErrorRecord.Exception.Response
  if ($null -eq $Response) { return $ErrorRecord.Exception.Message }
  try {
    $Reader = [IO.StreamReader]::new($Response.GetResponseStream())
    $Reader.ReadToEnd()
  } catch {
    $ErrorRecord.Exception.Message
  }
}

function Get-PropertyValue($Object, [string[]]$Names) {
  foreach ($Name in $Names) {
    $Current = $Object
    foreach ($Part in $Name.Split(".")) {
      if ($null -eq $Current) { break }
      $Property = $Current.PSObject.Properties[$Part]
      $Current = if ($Property) { $Property.Value } else { $null }
    }
    if ($null -ne $Current -and "$Current" -ne "") { return $Current }
  }
  "unknown"
}

function Invoke-RenderApi([string]$Method, [string]$Path, $Body = $null) {
  $Headers = @{
    Authorization = "Bearer $script:RenderApiKey"
    Accept = "application/json"
  }
  $Params = @{
    Method = $Method
    Uri = "$RenderApiBase$Path"
    Headers = $Headers
    TimeoutSec = 45
  }
  if ($null -ne $Body) {
    $Params.ContentType = "application/json"
    $Params.Body = ($Body | ConvertTo-Json -Depth 8)
  }
  try {
    Invoke-RestMethod @Params
  } catch {
    $Status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "unknown" }
    $BodyText = Redact-Secrets (Get-SafeErrorBody $_)
    Write-Host "Render API error status: $Status"
    if ($BodyText) { Write-Host "Render API safe response: $BodyText" }
    throw "Render API request failed: $Method $Path"
  }
}

function Invoke-PublicJson([string]$Path, [hashtable]$Headers = @{}, [string]$Method = "Get") {
  Invoke-RestMethod -Method $Method -Uri "$BackendUrl$Path" -Headers $Headers -TimeoutSec 120
}

function Get-EnvVarNames($Response) {
  $Rows = if ($Response -is [array]) { $Response } elseif ($Response.envVars) { $Response.envVars } elseif ($Response.items) { $Response.items } else { @() }
  foreach ($Row in $Rows) {
    $Name = Get-PropertyValue $Row @("key", "envVar.key", "name", "envVar.name")
    if ($Name -ne "unknown") { $Name }
  }
}

function Save-AdminToken {
  $Dir = Split-Path -Parent $AdminTokenPath
  New-Item -ItemType Directory -Force -Path $Dir | Out-Null
  Set-Content -LiteralPath $AdminTokenPath -Value $script:AdminToken -Encoding ascii -NoNewline
  Write-Host "ADMIN_REFRESH_TOKEN generated and stored locally in ignored runtime/secrets/"
}

function Wait-BackendReady {
  for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
    try {
      $Health = Invoke-PublicJson "/health"
      $Status = Invoke-PublicJson "/deployment/status"
      $Ready = $Health.status -eq "ok" -and $Status.api_env -eq "production" -and $Status.database_runtime_type -eq "postgres" -and $Status.production_ready
      Write-Host "- backend check ${Attempt}: status=$($Health.status), api_env=$($Status.api_env), database=$($Status.database_runtime_type), production_ready=$($Status.production_ready)"
      if ($Ready) { return $true }
    } catch {
      Write-Host "- backend check ${Attempt}: waiting"
    }
    Start-Sleep -Seconds 15
  }
  return $false
}

Write-Host "Repo: $RepoRoot"
Write-Host "Render service id: $ServiceId"
Write-Host "Backend URL: $BackendUrl"
$script:SecureKey = Read-Host "Paste Render API key, then press Enter:" -AsSecureString
$script:RenderApiKey = Convert-ToPlainText $script:SecureKey

try {
  Write-Host ""
  Write-Host "Verifying Render service"
  $ServiceResponse = Invoke-RenderApi "Get" "/services/$ServiceId"
  $Service = if ($ServiceResponse.service) { $ServiceResponse.service } else { $ServiceResponse }
  Write-Host "- name: $(Get-PropertyValue $Service @("name"))"
  Write-Host "- id: $(Get-PropertyValue $Service @("id"))"

  $script:AdminToken = New-AdminToken
  Save-AdminToken

  Write-Host ""
  Write-Host "Setting ADMIN_REFRESH_TOKEN on Render"
  $null = Invoke-RenderApi "Put" "/services/$ServiceId/env-vars/ADMIN_REFRESH_TOKEN" @{ value = $script:AdminToken }
  Write-Host "- ADMIN_REFRESH_TOKEN: updated/present"

  Write-Host ""
  Write-Host "Render env vars"
  $EnvResponse = Invoke-RenderApi "Get" "/services/$ServiceId/env-vars?limit=100"
  $Present = @(Get-EnvVarNames $EnvResponse)
  foreach ($Name in $RequiredEnvVars) {
    Write-Host "- ${Name}: $(if ($Present -contains $Name) { "present" } else { "missing" })"
  }

  Write-Host ""
  Write-Host "Triggering Render deploy"
  $DeployResponse = Invoke-RenderApi "Post" "/services/$ServiceId/deploys" @{ clearCache = "do_not_clear" }
  Write-Host "- deploy id: $(Get-PropertyValue $DeployResponse @("deploy.id", "id"))"
  Write-Host "- deploy status: $(Get-PropertyValue $DeployResponse @("deploy.status", "status"))"

  Write-Host ""
  Write-Host "Waiting for hosted backend"
  if (-not (Wait-BackendReady)) {
    throw "Timed out waiting for hosted backend readiness"
  }

  Write-Host ""
  Write-Host "Running hosted admin refresh"
  $Refresh = Invoke-PublicJson "/admin/refresh-jobs" @{ "X-Admin-Refresh-Token" = $script:AdminToken; "Content-Type" = "application/json" } "Post"
  foreach ($Key in @("sources_checked", "jobs_collected", "inserted", "duplicates_updated", "stale_jobs", "strong_excellent_matches", "report_generated")) {
    Write-Host "- ${Key}: $($Refresh.$Key)"
  }
  $Errors = if ($Refresh.source_errors) { $Refresh.source_errors.PSObject.Properties.Count } else { 0 }
  Write-Host "- source_errors: $Errors"

  Write-Host ""
  Write-Host "Verifying hosted digest and live data"
  $Report = Invoke-PublicJson "/reports/latest"
  $Jobs = Invoke-PublicJson "/jobs"
  $Queue = Invoke-PublicJson "/review/queue"
  $Stats = Invoke-PublicJson "/stats/overview"
  Write-Host "- report exists: $($Report.exists)"
  Write-Host "- report date: $($Report.date)"
  Write-Host "- summary keys: $(@($Report.summary.PSObject.Properties.Name).Count)"
  Write-Host "- jobs: $($Jobs.Count)"
  Write-Host "- stats total: $($Stats.total)"
  Write-Host "- needs review: $($Queue.needs_review.Count)"

  Write-Host ""
  Write-Host "Checking Vercel frontend"
  $Site = Invoke-WebRequest -UseBasicParsing -Uri $LiveSite -TimeoutSec 45
  Write-Host "- site HTTP: $($Site.StatusCode)"
  Write-Host "- Live API badge in HTML: $(if ($Site.Content -match "Live API") { "yes" } else { "check browser" })"
  Write-Host "- Demo Mode in HTML: $(if ($Site.Content -match "Demo Mode") { "yes" } else { "no" })"
  Write-Host "Open $LiveSite and confirm latest digest is visible."
} finally {
  Clear-Secrets
}

Write-Host ""
$null = Read-Host "Done. Press Enter to close"
