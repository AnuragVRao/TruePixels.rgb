<#
.SYNOPSIS
  Stop TruePixels.rgb: the API, the HTTPS front end and (by default) the database.

.DESCRIPTION
  All data is kept: accounts, images, results and the database volume.
  Nothing is deleted. (Never use "docker compose down -v" - that deletes data.)

.PARAMETER KeepDatabase
  Leave the PostgreSQL container running.

.EXAMPLE
  .\stop.ps1
  .\stop.ps1 -KeepDatabase
#>
param([switch]$KeepDatabase)

$Repo = $PSScriptRoot
Set-Location $Repo

Write-Host "`n==> API" -ForegroundColor Cyan
$stopped = $false
$owners = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $owners) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -match 'uvicorn app\.main:app') {
    # uvicorn may run under a parent launcher; stop both.
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    if ($parent -and $parent.CommandLine -match 'uvicorn app\.main:app') {
      Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue
    }
    $stopped = $true
  } elseif ($proc) {
    Write-Host "Port 8000 is used by something else ($($proc.Name)); left alone."
  }
}
# Close the API window(s) that start.ps1 opened.
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'TruePixels API' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
if ($stopped) { Write-Host 'API stopped.' } else { Write-Host 'The API was not running.' }

$dockerUp = $false
try { docker info *> $null; $dockerUp = ($LASTEXITCODE -eq 0) } catch { $dockerUp = $false }
if (-not $dockerUp) {
  Write-Host "`nDocker is not running, so Caddy and the database are already stopped." -ForegroundColor Green
  exit 0
}

Write-Host "`n==> HTTPS front end (Caddy)" -ForegroundColor Cyan
docker compose --env-file backend/.env --profile https-dev stop caddy-dev

if (-not $KeepDatabase) {
  Write-Host "`n==> Database" -ForegroundColor Cyan
  docker compose --env-file backend/.env stop db
}

Write-Host "`nTruePixels.rgb is stopped. Data is kept. Start it again with .\start.ps1 (or start.cmd)." -ForegroundColor Green
