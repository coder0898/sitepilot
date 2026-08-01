$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "SiteOps containers"
& docker compose ps
Write-Host ""
Write-Host "Supabase containers"
& docker ps --filter "name=supabase_" --format "{{.Names}}  {{.Status}}  {{.Ports}}" | Select-String "siteops-mvp"
Write-Host ""
$statusOutput = & npx supabase status -o env
$apiUrl = $statusOutput | ForEach-Object {
    if ($_ -match '^\s*(API_URL|SUPABASE_URL)\s*=\s*"?([^"]*)"?\s*$') { $matches[2] }
} | Select-Object -First 1

try {
    if (-not $apiUrl) { throw "Supabase API URL is unavailable." }
    $response = Invoke-WebRequest -UseBasicParsing -Uri "$apiUrl/auth/v1/health" -TimeoutSec 5
    Write-Host "Supabase Auth HTTP $([int]$response.StatusCode)"
} catch {
    Write-Host "Supabase Auth is not healthy."
    exit 1
}