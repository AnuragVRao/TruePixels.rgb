<#
.SYNOPSIS
  Apply pending Alembic migrations - only after a verified backup of the database being migrated.

.DESCRIPTION
  Called by start.ps1 (step 2); can also be run on its own from anywhere.

  1. Asks scripts/pending_migrations.py what is pending and WHICH database
     Alembic will migrate (DATABASE_URL). Nothing pending: exits 0.
  2. Refuses (exit 2) if any pending migration is ATTENDED_ONLY (a destructive
     contract step) and is not named in -ApplyAttendedMigration. An unattended
     start never applies one.
  3. Backs up THAT database to -BackupDir with a UTC timestamp, and verifies it:
       PostgreSQL - pg_dump -Fc inside the compose 'db' container, checked with
                    pg_restore --list there, copied out with 'docker compose cp'
                    (PowerShell 5.1 would corrupt binary output piped from a
                    native command), header 'PGDMP' checked on the host;
       SQLite     - the database file copied, header 'SQLite format 3' checked.
     A .sha256 file is written beside it. Any failure: exit 1, NOTHING migrated.
  4. alembic upgrade head. Failure: exit 1, and the backup path is printed.

.PARAMETER BackupDir
  Where backups go. Default: TruePixels-backups in your home folder (outside the
  repository), or TRUEPIXELS_BACKUP_DIR.

.PARAMETER ApplyAttendedMigration
  Revision id(s) of ATTENDED_ONLY migrations you have decided to apply now.

.PARAMETER Python
  The interpreter. Default: the repository's .venv.
#>
param(
  [string]$BackupDir = $(if ($env:TRUEPIXELS_BACKUP_DIR) { $env:TRUEPIXELS_BACKUP_DIR } else { Join-Path $HOME 'TruePixels-backups' }),
  [string[]]$ApplyAttendedMigration = @(),
  [string]$Python = ''
)

$ErrorActionPreference = 'Stop'
$Backend = Split-Path -Parent $PSScriptRoot
$Repo = Split-Path -Parent $Backend
if (-not $Python) { $Python = Join-Path $Repo '.venv\Scripts\python.exe' }
$Compose = @('compose', '--env-file', (Join-Path $Backend '.env'), '--project-directory', $Repo)

function Stop-Migration($text, $code = 1) { Write-Host "`nERROR: $text" -ForegroundColor Red; exit $code }

Push-Location $Backend
try { $raw = & $Python scripts/pending_migrations.py; $code = $LASTEXITCODE } finally { Pop-Location }
if ($code -ne 0) { Stop-Migration "Could not read the migration state: $raw" }
$state = $raw | ConvertFrom-Json
$pending = @($state.pending)

if ($pending.Count -eq 0) {
  Write-Host "Database is at head ($($state.head)); nothing to migrate."
  exit 0
}
Write-Host ("Pending on $($state.dialect) database '$($state.database)': " +
            (($pending | ForEach-Object { $_.revision }) -join ', ') + " (current: $($state.current))")

# ---- attended-only migrations are never applied unattended ----------------
$notAllowed = @($pending | Where-Object { $_.attended_only -and ($ApplyAttendedMigration -notcontains $_.revision) })
if ($notAllowed.Count -gt 0) {
  $list = ($notAllowed | ForEach-Object { "$($_.revision) - $($_.title)" }) -join "`n  "
  $ids = ($notAllowed | ForEach-Object { $_.revision }) -join ','
  Stop-Migration ("These migrations change data irreversibly and are never applied automatically:`n  $list`n" +
                  "Read the migration first; to apply it (a verified backup is still taken), run:`n" +
                  "  .\start.ps1 -ApplyAttendedMigration $ids") 2
}

# ---- verified backup of the database being migrated -------------------------
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$target = $pending[-1].revision
$from = if ($state.current) { $state.current } else { 'empty' }

if ($state.dialect -eq 'postgresql') {
  $name = "$($state.database)_pre-${target}_from-${from}_$stamp.dump"
  $backup = Join-Path $BackupDir $name
  $inContainer = "/tmp/$name"
  Write-Host "Backing up '$($state.database)' to $backup ..."
  & docker @Compose exec -T db sh -c "pg_dump -Fc -U `"`$POSTGRES_USER`" -d '$($state.database)' -f $inContainer && pg_restore --list $inContainer > /dev/null"
  if ($LASTEXITCODE -ne 0) { Stop-Migration 'pg_dump (or its pg_restore --list check) failed - nothing was migrated.' }
  & docker @Compose cp "db:$inContainer" "$backup"
  $copied = $LASTEXITCODE
  & docker @Compose exec -T db rm -f $inContainer | Out-Null
  if ($copied -ne 0 -or -not (Test-Path $backup)) { Stop-Migration 'Could not copy the dump out of the container - nothing was migrated.' }
  $magic = 'PGDMP'
} elseif ($state.dialect -eq 'sqlite' -and $state.sqlite_path) {
  $name = "$([System.IO.Path]::GetFileNameWithoutExtension($state.sqlite_path))_pre-${target}_from-${from}_$stamp.db"
  $backup = Join-Path $BackupDir $name
  Write-Host "Backing up $($state.sqlite_path) to $backup ..."
  Copy-Item -LiteralPath $state.sqlite_path -Destination $backup
  $magic = 'SQLite format 3'
} else {
  Stop-Migration "Do not know how to back up a '$($state.dialect)' database - nothing was migrated."
}

$size = (Get-Item -LiteralPath $backup).Length
$bytes = [System.IO.File]::ReadAllBytes($backup)
$header = if ($bytes.Length -ge $magic.Length) { [System.Text.Encoding]::ASCII.GetString($bytes, 0, $magic.Length) } else { '' }
if ($size -le 0 -or $header -ne $magic) { Stop-Migration "The backup at $backup is not valid - nothing was migrated." }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $backup).Hash.ToLower()
Set-Content -LiteralPath "$backup.sha256" -Value "$hash *$name" -Encoding ascii
Write-Host "Backup OK: $size bytes, sha256 $hash"

# ---- migrate ------------------------------------------------------------------
Push-Location $Backend
try { & $Python -m alembic upgrade head; $code = $LASTEXITCODE } finally { Pop-Location }
if ($code -ne 0) { Stop-Migration "alembic upgrade head failed (see above). Backup: $backup" }
Write-Host "Migrated to head. Backup kept at $backup"
exit 0
