<#
.SYNOPSIS
  Start TruePixels.rgb locally: database, API, HTTPS front end, browser.

.DESCRIPTION
  1. Docker Desktop (started if it is not running) and the PostgreSQL container.
  2. Pending database migrations (backend/scripts/migrate_with_backup.ps1).
     Whenever any are pending, a timestamped backup of the database being
     migrated (pg_dump, or a file copy for SQLite) is taken FIRST, to
     -BackupDir, and verified; if it fails, the start stops and nothing is
     migrated. Migrations marked ATTENDED_ONLY
     (destructive contract steps) are never applied by this script on its
     own: it stops and names them, unless -ApplyAttendedMigration lists them.
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

.PARAMETER BackupDir
  Where the pre-migration pg_dump goes. Default: TruePixels-backups in your
  home folder (outside the repository). Also read from TRUEPIXELS_BACKUP_DIR.

.PARAMETER ApplyAttendedMigration
  Revision id(s) of ATTENDED_ONLY migrations you have decided to apply now,
  e.g. -ApplyAttendedMigration 0007. Without it they are never applied.

.EXAMPLE
  .\start.ps1
  .\start.ps1 -ConsoleCodes -Build
  .\start.ps1 -ApplyAttendedMigration 0007
#>
param(
  [switch]$ConsoleCodes,
  [switch]$Build,
  [switch]$NoBrowser,
  [string]$BackupDir = $(if ($env:TRUEPIXELS_BACKUP_DIR) { $env:TRUEPIXELS_BACKUP_DIR } else { Join-Path $HOME 'TruePixels-backups' }),
  [string[]]$ApplyAttendedMigration = @()
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
# A verified, timestamped backup of the database being migrated is taken
# before ANY pending migration, and attended-only (destructive) migrations are
# never applied unless named with -ApplyAttendedMigration. See the script.
Step 'Database migrations'
& (Join-Path $Repo 'backend\scripts\migrate_with_backup.ps1') -BackupDir $BackupDir -ApplyAttendedMigration $ApplyAttendedMigration -Python $Python
if ($LASTEXITCODE -ne 0) { Fail 'Migrations were not applied (see above). Nothing else was started.' }

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
$stale = $false
if (Test-Path $dist) {
  # Rebuild whenever any front-end source is newer than the last build, so
  # https://localhost always shows the current code.
  $builtAt = (Get-Item $dist).LastWriteTime
  $fe = Join-Path $Repo 'frontend'
  $sources = @(Get-ChildItem -Path (Join-Path $fe 'src'), (Join-Path $fe 'public') -Recurse -File -ErrorAction SilentlyContinue) +
             @(Get-Item (Join-Path $fe 'index.html'), (Join-Path $fe 'package.json'), (Join-Path $fe 'vite.config.ts'), (Join-Path $fe 'tailwind.config.js') -ErrorAction SilentlyContinue)
  $newer = $sources | Where-Object { $_.LastWriteTime -gt $builtAt }
  if ($newer) { $stale = $true; Write-Host "Front-end sources changed since the last build ($(@($newer).Count) file(s))." }
}
if ($Build -or $stale -or -not (Test-Path $dist)) {
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
