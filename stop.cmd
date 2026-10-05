@echo off
rem Double-click to stop TruePixels.rgb (data is kept). Option: stop.cmd -KeepDatabase
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
pause
