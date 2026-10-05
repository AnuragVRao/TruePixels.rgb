<#
.SYNOPSIS
  Start TruePixels.rgb locally: database, API, HTTPS front end, browser.

.DESCRIPTION
  1. Docker Desktop (started if it is not running) and the PostgreSQL container.
  2. Pending database migrations (alembic upgrade head).
  3. The API in its own window, "TruePixels API". Keep it open: closing it
     stops the API, and OTP codes appear there when e-mail is not used.
  4. The front-end build, if frontend/dist does not exist yet (or -Build).
  5. Caddy (the https-dev profile), then opens https://localhost.

  Running it again is safe: anything already running is left as it is.

.PARAMETER ConsoleCodes
  Print sign-in codes in the API window instead of e-mailing them
  (sets EMAIL_BACKEND=console for this run only; needs ENVIRONMENT=development).

.PARAMETER Build
  Rebuild the front end before starting (after changing frontend code).

.PARAMETER NoBrowser
  Do not open the browser at the end.

.EXAMPLE
  .\start.ps1
  .\start.ps1 -ConsoleCodes -Build
#>
param(
  [switch]$ConsoleCodes,
  [switch]$Build,
  [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
$EnvFile = Join-Path $Repo 'backend\.env'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Python)) { Fail "Python venv not found at $Python. See readme.md > Setup." }
if (-not (Test-Path $EnvFile)) { Fail "backend\.env not found. Copy backend\.env.example and fill it in (readme.md > Setup)." }

Set-Location $Repo

# ---- 1. Docker + database -------------------------------------------------
Step 'Docker Desktop'
$dockerUp = $false
try { docker info *> $null; $dockerUp = ($LASTEXITCODE -eq 0) } catch { $dockerUp = $false }
if (-not $dockerUp) {
  $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if (-not (Test-Path $desktop)) { Fail 'Docker is not running and Docker Desktop was not found. Start Docker Desktop and try again.' }
  Write-Host 'Starting Docker Desktop (this can take a minute)...'
  Start-Process $desktop
  for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    try { docker info *> $null; if ($LASTEXITCODE -eq 0) { $dockerUp = $true; break } } catch { }
  }
  if (-not $dockerUp) { Fail 'Docker Desktop did not become ready in 3 minutes.' }
}
Write-Host 'Docker is running.'

Step 'Database (PostgreSQL)'
docker compose --env-file backend/.env up -d db
if ($LASTEXITCODE -ne 0) { Fail 'Could not start the database container.' }
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
  $status = docker compose --env-file backend/.env ps db --format '{{.Status}}'
  if ($status -match 'healthy') { $healthy = $true; break }
  Start-Sleep -Seconds 2
}
if (-not $healthy) { Fail 'The database did not become healthy in 2 minutes.' }
Write-Host 'Database is healthy.'

# ---- 2. Migrations --------------------------------------------------------
Step 'Database migrations'
Push-Location (Join-Path $Repo 'backend')
& $Python -m alembic upgrade head
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail 'alembic upgrade head failed (see the output above).' }

# ---- 3. API ---------------------------------------------------------------
Step 'API (http://127.0.0.1:8000, in its own window)'
$listening = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
if ($listening) {
  Write-Host 'Something is already listening on port 8000 - assuming the API is running.'
} else {
  $emailLine = ''
  $title = 'TruePixels API'
  if ($ConsoleCodes) { $emailLine = "`$env:EMAIL_BACKEND = 'console'; "; $title = 'TruePixels API (console codes)' }
  $backend = Join-Path $Repo 'backend'
  $cmd = "`$host.UI.RawUI.WindowTitle = '$title'; $emailLine" +
         "Set-Location '$backend'; " +
         "Write-Host 'TruePixels API - keep this window open. Closing it stops the API. Stop everything with stop.ps1.' -ForegroundColor Yellow; " +
         "& '$Python' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers"
  Start-Process powershell -ArgumentList '-NoExit', '-Command', $cmd -WorkingDirectory $backend | Out-Null
}

Write-Host 'Waiting for the models to load (about 10-30 s)...'
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
  try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/ready' -UseBasicParsing -TimeoutSec 3
    if ($r.StatusCode -eq 200) { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 2
}
if (-not $ready) { Fail 'The API did not become ready in 4 minutes. Look at the "TruePixels API" window for the error.' }
Write-Host 'API is ready.'

# ---- 4. Front-end build ---------------------------------------------------
$dist = Join-Path $Repo 'frontend\dist\index.html'
if ($Build -or -not (Test-Path $dist)) {
  Step 'Building the front end'
  Push-Location (Join-Path $Repo 'frontend')
  npm run build
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0) { Fail 'npm run build failed.' }
}

# ---- 5. HTTPS front end ---------------------------------------------------
Step 'HTTPS front end (Caddy)'
docker compose --env-file backend/.env --profile https-dev up -d caddy-dev
if ($LASTEXITCODE -ne 0) { Fail 'Could not start Caddy. Are ports 80/443 free? (readme.md > HTTPS)' }

Write-Host "`nTruePixels.rgb is running at https://localhost" -ForegroundColor Green
Write-Host 'Stop it with .\stop.ps1 (or stop.cmd).'
if (-not $NoBrowser) { Start-Process 'https://localhost' }
