$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$TokenPath = Join-Path $RepoRoot "runtime\secrets\admin_refresh_token.local.txt"
$Repo = "khoi9034/GisJobPortal"
$SecretName = "ADMIN_REFRESH_TOKEN"

function Convert-ToPlainText([securestring]$SecureValue) {
  $Bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
  try {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Bstr)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Bstr)
  }
}

function Read-AdminToken {
  if (Test-Path $TokenPath) {
    return (Get-Content -Raw -LiteralPath $TokenPath).Trim()
  }
  $Secure = Read-Host "Paste ADMIN_REFRESH_TOKEN, then press Enter" -AsSecureString
  return Convert-ToPlainText $Secure
}

Write-Host "Repo: $Repo"
Write-Host "Secret: $SecretName"

$Gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $Gh) {
  Write-Host "GitHub CLI not found. Install gh, then run:"
  Write-Host "Get-Content runtime\secrets\admin_refresh_token.local.txt | gh secret set ADMIN_REFRESH_TOKEN --repo khoi9034/GisJobPortal --body-file -"
  exit 1
}

$AdminToken = Read-AdminToken
if ([string]::IsNullOrWhiteSpace($AdminToken)) {
  throw "ADMIN_REFRESH_TOKEN is empty."
}

$HadGhToken = -not [string]::IsNullOrWhiteSpace($env:GH_TOKEN)
try {
  & gh auth status --hostname github.com *> $null
  if ($LASTEXITCODE -ne 0 -and -not $HadGhToken) {
    $SecureGithubToken = Read-Host "Paste GitHub token, then press Enter" -AsSecureString
    $env:GH_TOKEN = Convert-ToPlainText $SecureGithubToken
  }

  $AdminToken | & gh secret set $SecretName --repo $Repo --body-file -
  if ($LASTEXITCODE -ne 0) {
    throw "gh secret set failed."
  }
  Write-Host "$SecretName repository secret set for $Repo."
} finally {
  $AdminToken = $null
  if (-not $HadGhToken) {
    $env:GH_TOKEN = $null
  }
}
