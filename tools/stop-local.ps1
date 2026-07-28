$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

& docker compose down
if ($LASTEXITCODE -ne 0) { throw "Could not stop SiteOps containers." }

& npx supabase stop
if ($LASTEXITCODE -ne 0) { throw "Could not stop the local Supabase stack." }
