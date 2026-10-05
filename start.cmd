@echo off
rem Double-click to start TruePixels.rgb. Options: start.cmd -ConsoleCodes -Build -NoBrowser
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
