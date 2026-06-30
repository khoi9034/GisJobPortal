param(
    [string]$RepoRoot = "C:\Dev\GisJobPortal"
)

$ErrorActionPreference = "Stop"
$EnvPath = Join-Path $RepoRoot "backend\.env"
$Pairs = [ordered]@{
    "ADZUNA_APP_ID" = "Adzuna app id"
    "ADZUNA_APP_KEY" = "Adzuna app key"
    "RAPIDAPI_KEY" = "RapidAPI key for JSearch"
    "SERPAPI_KEY" = "SerpApi key"
}

function ConvertFrom-SecureInput {
    param([securestring]$Value)
    $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr)
    }
}

function Set-EnvLine {
    param([string[]]$Lines, [string]$Name, [string]$Value)
    $Pattern = "^$([regex]::Escape($Name))="
    $Line = "$Name=$Value"
    if ($Lines | Where-Object { $_ -match $Pattern }) {
        return $Lines | ForEach-Object { if ($_ -match $Pattern) { $Line } else { $_ } }
    }
    return @($Lines + $Line)
}

if (-not (Test-Path $RepoRoot)) {
    throw "Repo root not found: $RepoRoot"
}

if (-not (Test-Path $EnvPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $EnvPath) | Out-Null
    Set-Content -Path $EnvPath -Value @(
        "DATABASE_URL=sqlite:///./data/jobs.sqlite3",
        "API_ENV=local",
        "CORS_ORIGINS=http://localhost:3000,https://gis-job-portal.vercel.app"
    ) -Encoding utf8
}

$Lines = @(Get-Content $EnvPath -ErrorAction SilentlyContinue)
foreach ($Name in $Pairs.Keys) {
    $Secret = Read-Host "Paste $($Pairs[$Name]) or press Enter to skip" -AsSecureString
    $Value = ConvertFrom-SecureInput $Secret
    if ([string]::IsNullOrWhiteSpace($Value)) {
        Write-Host "$Name skipped."
        continue
    }
    $Lines = Set-EnvLine $Lines $Name $Value
    Write-Host "$Name saved to backend/.env."
}

Set-Content -Path $EnvPath -Value $Lines -Encoding utf8
Write-Host "Done. backend/.env is local-only and ignored by Git."
