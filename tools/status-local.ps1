$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "SiteOps containers"
& docker compose ps
Write-Host ""
Write-Host "Supabase containers"
& docker ps --filter "name=supabase_" --format "{{.Names}}  {{.Status}}  {{.Ports}}" | Select-String "siteops-mvp"
Write-Host ""
try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:54321/auth/v1/health" -TimeoutSec 5
    Write-Host "Supabase Auth HTTP $([int]$response.StatusCode)"
} catch {
    Write-Host "Supabase Auth is not healthy."
    exit 1
}