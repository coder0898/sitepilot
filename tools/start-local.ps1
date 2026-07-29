$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Read-ExistingEnv {
    $result = @{}
    if (Test-Path ".env") {
        Get-Content ".env" | ForEach-Object {
            if ($_ -match '^([^#=]+)=(.*)$') {
                $result[$matches[1].Trim()] = $matches[2].Trim()
            }
        }
    }
    return $result
}

function First-Value {
    param([hashtable]$Values, [string[]]$Names)
    foreach ($name in $Names) {
        if ($Values.ContainsKey($name) -and -not [string]::IsNullOrWhiteSpace($Values[$name])) {
            return $Values[$name]
        }
    }
    return $null
}

Write-Host "Starting the official local Supabase Docker stack..."
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$supabaseStartOutput = & npx supabase start -x realtime,storage-api,imgproxy,postgres-meta,studio,edge-runtime,logflare,vector,supavisor,postgrest 2>&1
$supabaseStartExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($supabaseStartExitCode -ne 0) {
    $supabaseStartOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "Supabase local stack failed to start. Review the Supabase output above."
}

Write-Host "Applying pending Supabase migrations..."
& npx supabase migration up --local
if ($LASTEXITCODE -ne 0) {
    throw "Pending Supabase migrations could not be applied."
}

$statusOutput = & npx supabase status -o env
if ($LASTEXITCODE -ne 0) {
    throw "Could not read local Supabase credentials."
}

$local = @{}
$statusOutput | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*"?([^"]*)"?\s*$') {
        $local[$matches[1]] = $matches[2]
    }
}

$apiUrl = First-Value $local @("API_URL", "SUPABASE_URL")
$publishableKey = First-Value $local @("PUBLISHABLE_KEY", "ANON_KEY")
$secretKey = First-Value $local @("SECRET_KEY", "SERVICE_ROLE_KEY")
$dbUrl = First-Value $local @("DB_URL")
$mailpitUrl = First-Value $local @("INBUCKET_URL")

if (-not $apiUrl -or -not $publishableKey -or -not $secretKey -or -not $dbUrl) {
    throw "Supabase started, but the required local API keys or database URL were not returned."
}

$backendApiUrl = $apiUrl -replace '^https?://(127\.0\.0\.1|localhost)', 'http://host.docker.internal'
$backendDbUrl = $dbUrl -replace '^postgresql://', 'postgresql+psycopg://'
$backendDbUrl = $backendDbUrl -replace '@(127\.0\.0\.1|localhost):', '@host.docker.internal:'

$existing = Read-ExistingEnv
$bootstrapEmail = First-Value $existing @("BOOTSTRAP_SUPER_ADMIN_EMAIL")
$bootstrapPassword = First-Value $existing @("BOOTSTRAP_SUPER_ADMIN_PASSWORD")
$migrationPassword = First-Value $existing @("MIGRATION_TEMP_PASSWORD")

if (-not $bootstrapEmail) { $bootstrapEmail = "superadmin@siteops.local" }
if (-not $bootstrapPassword) { $bootstrapPassword = "LocalSiteOps!2026" }
if (-not $migrationPassword) { $migrationPassword = "LocalMigration!2026" }

$envLines = @(
    "# Generated for the local Supabase CLI stack. Git ignored.",
    "SUPABASE_PUBLIC_URL=$apiUrl",
    "SUPABASE_BACKEND_URL=$backendApiUrl",
    "SUPABASE_PUBLISHABLE_KEY=$publishableKey",
    "SUPABASE_SECRET_KEY=$secretKey",
    "FRONTEND_URL=http://localhost:3000",
    "DATABASE_URL=$backendDbUrl",
    "",
    "BOOTSTRAP_SUPER_ADMIN_EMAIL=$bootstrapEmail",
    "BOOTSTRAP_SUPER_ADMIN_PASSWORD=$bootstrapPassword",
    "MIGRATION_TEMP_PASSWORD=$migrationPassword",
    "",
    "VITE_API_BASE=http://localhost:8000"
)
[System.IO.File]::WriteAllLines((Join-Path $repoRoot ".env"), $envLines, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Building SiteOps against local Supabase Auth and PostgreSQL..."
& docker compose down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "Could not stop the previous SiteOps stack." }

& docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw "SiteOps containers failed to start." }

Write-Host ""
Write-Host "Local SiteOps is starting."
Write-Host "Portal: http://localhost:3000"
if ($mailpitUrl) { Write-Host "Local email inbox: $mailpitUrl" }
Write-Host "Super Admin: $bootstrapEmail"
Write-Host "Run 'npm run local:status' to verify health."
