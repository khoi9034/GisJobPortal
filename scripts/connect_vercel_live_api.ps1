$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ProjectName = "gis-job-portal"
$ProjectId = "prj_7rRCF8pTAJBrxMQZtsjBgvNYiKGI"
$TeamId = "team_NnrpDjazbXYZNE9Sqb9iTIKv"
$BackendUrl = "https://gisjobportal.onrender.com"
$LiveSite = "https://gis-job-portal.vercel.app"
$EnvEndpoint = "https://api.vercel.com/v10/projects/$ProjectId/env?teamId=$TeamId"
$Targets = @("production", "preview", "development")

trap {
  Clear-VercelToken
  Write-Host ""
  Write-Host "Vercel connection failed: $($_.Exception.Message)"
  Show-FailureHint "$($_.Exception.Message)"
  Write-Host "No token was saved. Check the message above, then retry this script."
  $null = Read-Host "Press Enter to close"
  exit 1
}

function Clear-VercelToken {
  $script:Token = $null
  $script:SecureToken = $null
}

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
  }
}

function Redact-Secret([string]$Text) {
  if ($script:Token) { return $Text.Replace($script:Token, "[redacted]") }
  $Text
}

function Show-FailureHint([string]$Text) {
  if ($Text -match "404|not found") {
    Write-Host "404 hint: check project id, team id, endpoint version, and token team access."
  } elseif ($Text -match "401|403|unauthorized|forbidden") {
    Write-Host "Auth hint: check Vercel token permissions and team access."
  }
}

function Get-SafeErrorBody($ErrorRecord) {
  $Response = $ErrorRecord.Exception.Response
  if ($null -eq $Response) { return $ErrorRecord.Exception.Message }
  try {
    $Stream = $Response.GetResponseStream()
    if ($null -eq $Stream) { return $ErrorRecord.Exception.Message }
    $Reader = [IO.StreamReader]::new($Stream)
    $Reader.ReadToEnd()
  } catch {
    $ErrorRecord.Exception.Message
  }
}

function Invoke-VercelApi([string]$Method, [string]$Uri, $Body = $null) {
  $Headers = @{
    Authorization = "Bearer $script:Token"
    Accept = "application/json"
    "Content-Type" = "application/json"
  }
  $Params = @{
    Method = $Method
    Uri = $Uri
    Headers = $Headers
    TimeoutSec = 45
  }
  if ($null -ne $Body) {
    $Params.Body = ($Body | ConvertTo-Json -Depth 8)
  }
  try {
    Invoke-RestMethod @Params
  } catch {
    $Status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "unknown" }
    $SafeBody = Redact-Secret (Get-SafeErrorBody $_)
    Write-Host "Vercel API error status: $Status"
    if ($SafeBody) { Write-Host "Vercel API safe response: $SafeBody" }
    Show-FailureHint "$Status $SafeBody"
    throw "Vercel API request failed: $Method $Uri"
  }
}

function Get-EnvRows($Response) {
  if ($Response -is [array]) { return @($Response) }
  foreach ($Name in @("envs", "envVars", "items")) {
    $Prop = $Response.PSObject.Properties[$Name]
    if ($Prop) { return @($Prop.Value) }
  }
  @()
}

function Format-Targets($Value) {
  if ($Value -is [array]) { return ($Value -join ", ") }
  if ($null -eq $Value -or "$Value" -eq "") { return "unknown" }
  "$Value"
}

function Test-BackendReady {
  $Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path $Python)) { $Python = "python" }
  $Output = & $Python "scripts\check_hosted_backend.py" "--url" $BackendUrl 2>&1
  $ExitCode = $LASTEXITCODE
  $Output | ForEach-Object { Write-Host $_ }
  return $ExitCode -eq 0 -and ($Output -match "production ready: yes")
}

function Set-VercelEnv([string]$Name, [string]$Value, [string]$Comment) {
  $Body = @{
    key = $Name
    value = $Value
    type = "plain"
    target = $Targets
    comment = $Comment
  }
  $null = Invoke-VercelApi "Post" "$EnvEndpoint&upsert=true" $Body
  Write-Host "- ${Name}: updated/created for $($Targets -join ", ")"
}

function Confirm-VercelEnv {
  $Response = Invoke-VercelApi "Get" $EnvEndpoint
  $Rows = @(Get-EnvRows $Response)
  foreach ($Name in @("NEXT_PUBLIC_API_MODE", "NEXT_PUBLIC_API_BASE_URL")) {
    $Matches = @($Rows | Where-Object { $_.key -eq $Name })
    if ($Matches.Count -eq 0) { throw "Missing Vercel env var after update: $Name" }
    foreach ($Row in $Matches) {
      $TargetsText = Format-Targets $Row.target
      $UpdatedAt = if ($Row.updatedAt) { $Row.updatedAt } else { "unknown" }
      Write-Host "- ${Name}: targets=$TargetsText updatedAt=$UpdatedAt"
    }
  }
}

Set-Location $RepoRoot
Write-Host "This will set Vercel live API environment variables for '$ProjectName'."
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
$script:SecureToken = Read-Host "Paste Vercel token, then press Enter" -AsSecureString
$script:Token = Convert-ToPlainText $script:SecureToken

try {
  Write-Host ""
  Write-Host "Verifying Vercel project access"
  $null = Invoke-VercelApi "Get" $EnvEndpoint
  Write-Host "- access ok"

  Write-Host ""
  Write-Host "Upserting Vercel environment variables"
  Set-VercelEnv "NEXT_PUBLIC_API_MODE" "api" "Use hosted Render API for real job data"
  Set-VercelEnv "NEXT_PUBLIC_API_BASE_URL" $BackendUrl "Hosted GIS Job Portal backend API"

  Write-Host ""
  Write-Host "Verifying environment variables exist"
  Confirm-VercelEnv

  Write-Host ""
  Write-Host "Manual redeploy required:"
  Write-Host "1. Open Vercel dashboard -> gis-job-portal -> Deployments."
  Write-Host "2. Open the latest production deployment."
  Write-Host "3. Click Redeploy."
  Write-Host "4. After it finishes, refresh $LiveSite and confirm the badge says Live API."
} finally {
  Clear-VercelToken
}

Write-Host ""
$null = Read-Host "Done. Press Enter to close"
