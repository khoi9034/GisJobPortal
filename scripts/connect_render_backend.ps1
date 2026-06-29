$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$ServiceId = "srv-d90stu3sq97s739mpta0"
$BackendUrl = "https://gisjobportal.onrender.com"
$RenderApiBase = "https://api.render.com/v1"
$RequiredEnvVars = @(
  "DATABASE_URL",
  "API_ENV",
  "CORS_ORIGINS",
  "USAJOBS_USER_AGENT",
  "USAJOBS_AUTHORIZATION_KEY"
)

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
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

function Invoke-RenderApi($Method, $Path, $Body = $null) {
  $Headers = @{
    Authorization = "Bearer $ApiKey"
    Accept = "application/json"
  }
  $Params = @{
    Method = $Method
    Uri = "$RenderApiBase$Path"
    Headers = $Headers
    TimeoutSec = 30
  }
  if ($null -ne $Body) {
    $Params.ContentType = "application/json"
    $Params.Body = ($Body | ConvertTo-Json -Depth 6)
  }
  Invoke-RestMethod @Params
}

function Invoke-PublicJson($Path) {
  try {
    Invoke-RestMethod -Method Get -Uri "$BackendUrl$Path" -TimeoutSec 45
  } catch {
    $StatusCode = $null
    if ($_.Exception.Response) {
      $StatusCode = [int]$_.Exception.Response.StatusCode
    }
    if ($StatusCode -in @(502, 503) -or $_.Exception.Message -match "timed out|timeout") {
      Write-Host "Render service may be waking up. Retry in a minute."
    } else {
      Write-Host "Backend check failed for ${Path}: $($_.Exception.Message)"
    }
    $null
  }
}

function Get-EnvVarNames($Response) {
  $Rows = if ($Response -is [array]) { $Response } elseif ($Response.envVars) { $Response.envVars } elseif ($Response.items) { $Response.items } else { @() }
  foreach ($Row in $Rows) {
    $Name = Get-PropertyValue $Row @("key", "envVar.key", "name", "envVar.name")
    if ($Name -ne "unknown") { $Name }
  }
}

Write-Host "Repo: $RepoRoot"
Write-Host "Render service id: $ServiceId"
Write-Host "Backend URL: $BackendUrl"
$SecureKey = Read-Host "Paste Render API key, then press Enter:" -AsSecureString
$ApiKey = Convert-ToPlainText $SecureKey

try {
  Write-Host ""
  Write-Host "Render service"
  $ServiceResponse = Invoke-RenderApi "Get" "/services/$ServiceId"
  $Service = if ($ServiceResponse.service) { $ServiceResponse.service } else { $ServiceResponse }
  Write-Host "- name: $(Get-PropertyValue $Service @("name"))"
  Write-Host "- id: $(Get-PropertyValue $Service @("id"))"
  Write-Host "- type: $(Get-PropertyValue $Service @("type"))"
  Write-Host "- repo: $(Get-PropertyValue $Service @("repo", "repoDetails.name", "serviceDetails.repo"))"
  Write-Host "- branch: $(Get-PropertyValue $Service @("branch", "repoDetails.branch", "serviceDetails.branch"))"
  Write-Host "- deploy status: $(Get-PropertyValue $Service @("deployStatus", "serviceDetails.deployStatus", "suspended"))"
  Write-Host "- service URL: $(Get-PropertyValue $Service @("serviceDetails.url", "url"))"

  Write-Host ""
  Write-Host "Render env vars"
  try {
    $EnvResponse = Invoke-RenderApi "Get" "/services/$ServiceId/env-vars?limit=100"
    $Present = @(Get-EnvVarNames $EnvResponse)
    foreach ($Name in $RequiredEnvVars) {
      Write-Host "- ${Name}: $(if ($Present -contains $Name) { "present" } else { "missing" })"
    }
    $Missing = @($RequiredEnvVars | Where-Object { $Present -notcontains $_ })
    if ($Missing.Count -gt 0) {
      Write-Host "Add missing env vars in Render dashboard: $($Missing -join ", ")"
    }
  } catch {
    Write-Host "Could not check Render env vars: $($_.Exception.Message)"
  }

  Write-Host ""
  Write-Host "Hosted backend"
  $Health = Invoke-PublicJson "/health"
  $Status = Invoke-PublicJson "/deployment/status"
  $Jobs = Invoke-PublicJson "/jobs"
  if ($Health) { Write-Host "- health status: $($Health.status)" }
  if ($Status) {
    Write-Host "- api_env: $($Status.api_env)"
    Write-Host "- database_url_present: $($Status.database_url_present)"
    Write-Host "- database_url_scheme: $($Status.database_url_scheme)"
    Write-Host "- database_runtime_type: $($Status.database_runtime_type)"
    Write-Host "- real source count: $($Status.real_sources_enabled)"
    if ($Status.production_blockers) {
      Write-Host "- production blockers: $($Status.production_blockers -join ", ")"
    }
  }
  if ($Jobs) {
    $RealJobs = @($Jobs | Where-Object { $_.source -notin @("Demo", "Sample GIS Jobs") })
    Write-Host "- job count: $($Jobs.Count)"
    Write-Host "- real job count: $($RealJobs.Count)"
  }
  $RealSourceCount = if ($Status -and $Status.real_sources_enabled) { [int]$Status.real_sources_enabled } else { 0 }
  $RuntimeType = if ($Status.database_runtime_type) { $Status.database_runtime_type } else { $Status.database_type }
  $BlockerCount = if ($Status.production_blockers) { @($Status.production_blockers).Count } else { 0 }
  $ProductionReady = $Health.status -eq "ok" -and $Status.api_env -eq "production" -and $RuntimeType -eq "postgres" -and $RealSourceCount -gt 0 -and $BlockerCount -eq 0 -and $Jobs -and @($Jobs | Where-Object { $_.source -notin @("Demo", "Sample GIS Jobs") }).Count -gt 0
  Write-Host "- production-ready gate: $(if ($ProductionReady) { "pass" } else { "fail" })"
  if ($RuntimeType -eq "sqlite") {
    Write-Host "SQLite diagnosis: check DATABASE_URL is present, uses a passworded Neon URL, the service was redeployed after env changes, and psycopg installed from requirements.txt."
    Write-Host "Expected DATABASE_URL format: postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require"
  }

  Write-Host ""
  $Deploy = Read-Host "Trigger a new deploy now? y/n"
  if ($Deploy -eq "y") {
    $DeployResponse = Invoke-RenderApi "Post" "/services/$ServiceId/deploys"
    Write-Host "Deploy triggered: $(Get-PropertyValue $DeployResponse @("deploy.id", "id", "deploy.status", "status"))"
  } else {
    Write-Host "Deploy not triggered. Trigger deploy from the Render dashboard if needed."
  }
} finally {
  $ApiKey = $null
  $SecureKey = $null
}
