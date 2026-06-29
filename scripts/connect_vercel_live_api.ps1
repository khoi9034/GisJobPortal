$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$ProjectName = "gis-job-portal"
$ProjectId = "prj_7rRCF8pTAJBrxMQZtsjBgvNYiKGI"
$TeamId = "team_NnrpDjazbXYZNE9Sqb9iTIKv"
$BackendUrl = "https://gisjobportal.onrender.com"
$LiveSite = "https://gis-job-portal.vercel.app"
$VercelApiBase = "https://api.vercel.com"
$Targets = @("production", "preview", "development")

trap {
  $env:VERCEL_TOKEN = $null
  $Token = $null
  $SecureToken = $null
  Write-Host ""
  Write-Host "Vercel connection failed: $($_.Exception.Message)"
  Write-Host "No token was saved. Check the message above, then retry this script."
  $null = Read-Host "Press Enter to close"
  exit 1
}

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
  }
}

function Invoke-VercelApi($Method, $Path, $Body = $null) {
  $Headers = @{
    Authorization = "Bearer $env:VERCEL_TOKEN"
    Accept = "application/json"
  }
  $Params = @{
    Method = $Method
    Uri = "$VercelApiBase$Path"
    Headers = $Headers
    TimeoutSec = 45
  }
  if ($null -ne $Body) {
    $Params.ContentType = "application/json"
    $Params.Body = ($Body | ConvertTo-Json -Depth 8)
  }
  Invoke-RestMethod @Params
}

function Get-Prop($Object, [string[]]$Names) {
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

function Test-BackendReady {
  $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path $Python)) { $Python = "python" }
  $Output = & $Python "scripts\check_hosted_backend.py" "--url" $BackendUrl 2>&1
  $ExitCode = $LASTEXITCODE
  $Output | ForEach-Object { Write-Host $_ }
  return $ExitCode -eq 0 -and ($Output -match "production ready: yes")
}

function Set-VercelEnv($Name, $Value) {
  $Body = @{
    key = $Name
    value = $Value
    type = "plain"
    target = $Targets
    comment = "GisJobPortal live API setting"
  }
  $Response = Invoke-VercelApi "Post" "/v10/projects/$ProjectId/env?upsert=true&teamId=$TeamId" $Body
  $Failed = @($Response.failed)
  if ($Failed.Count -gt 0) {
    throw "Vercel env update failed for $Name."
  }
  Write-Host "- ${Name}: set for $($Targets -join ", ")"
}

function Get-LatestProductionDeployment {
  $Response = Invoke-VercelApi "Get" "/v7/deployments?projectId=$ProjectId&target=production&limit=1&teamId=$TeamId"
  $Deployments = @($Response.deployments)
  if ($Deployments.Count -eq 0) { return $null }
  $Deployments[0]
}

function Wait-ForDeployment($DeploymentId) {
  for ($Attempt = 1; $Attempt -le 12; $Attempt++) {
    Start-Sleep -Seconds 20
    $Latest = Get-LatestProductionDeployment
    $LatestId = Get-Prop $Latest @("uid", "id")
    $State = Get-Prop $Latest @("state", "readyState")
    if ($LatestId -eq $DeploymentId -or $Attempt -eq 1) {
      Write-Host "- deployment state: $State"
    }
    if ($LatestId -eq $DeploymentId -and $State -eq "READY") { return $true }
    if ($LatestId -eq $DeploymentId -and $State -in @("ERROR", "CANCELED")) { return $false }
  }
  return $false
}

Write-Host "This will connect Vercel project '$ProjectName' to the live Render API."
Write-Host "- project id: $ProjectId"
Write-Host "- team id: $TeamId"
Write-Host "- backend: $BackendUrl"
Write-Host "- live site: $LiveSite"
Write-Host ""
Write-Host "Checking backend readiness before touching Vercel..."

if (-not (Test-BackendReady)) {
  Write-Host "Backend is not production-ready. Vercel was not changed."
  $null = Read-Host "Press Enter to close"
  exit 1
}

Write-Host ""
$SecureToken = Read-Host "Paste Vercel token, then press Enter:" -AsSecureString
$Token = Convert-ToPlainText $SecureToken
$env:VERCEL_TOKEN = $Token

try {
  Write-Host ""
  Write-Host "Vercel project"
  $Project = Invoke-VercelApi "Get" "/v9/projects/$ProjectId?teamId=$TeamId"
  Write-Host "- name: $(Get-Prop $Project @("name"))"
  Write-Host "- id: $(Get-Prop $Project @("id"))"
  Write-Host "- framework: $(Get-Prop $Project @("framework"))"
  Write-Host "- root directory: $(Get-Prop $Project @("rootDirectory", "settings.rootDirectory"))"

  Write-Host ""
  Write-Host "Setting Vercel environment variables"
  Set-VercelEnv "NEXT_PUBLIC_API_MODE" "api"
  Set-VercelEnv "NEXT_PUBLIC_API_BASE_URL" $BackendUrl

  Write-Host ""
  Write-Host "Triggering production redeploy"
  $Previous = Get-LatestProductionDeployment
  if ($null -eq $Previous) {
    throw "No production deployment found to redeploy. Trigger deploy from the Vercel dashboard."
  }
  $PreviousId = Get-Prop $Previous @("uid", "id")
  $DeployBody = @{
    deploymentId = $PreviousId
    name = $ProjectName
    project = $ProjectId
    target = "production"
    withLatestCommit = $true
  }
  $Deploy = Invoke-VercelApi "Post" "/v13/deployments?teamId=$TeamId" $DeployBody
  $DeployId = Get-Prop $Deploy @("uid", "id")
  $DeployUrl = Get-Prop $Deploy @("url")
  Write-Host "- deployment id: $DeployId"
  Write-Host "- deployment url: $DeployUrl"

  if (Wait-ForDeployment $DeployId) {
    Write-Host "- deployment ready"
    try {
      $Response = Invoke-WebRequest -UseBasicParsing -Uri $LiveSite -TimeoutSec 30
      Write-Host "- live site HTTP: $($Response.StatusCode)"
      Write-Host "Expected result: the dashboard badge says Live API and real jobs load from $BackendUrl."
    } catch {
      Write-Host "Live site check failed: $($_.Exception.Message)"
    }
  } else {
    Write-Host "Deployment was triggered but did not become ready during this check. Check Vercel Deployments."
  }
} finally {
  $env:VERCEL_TOKEN = $null
  $Token = $null
  $SecureToken = $null
}

Write-Host ""
$null = Read-Host "Done. Press Enter to close"
