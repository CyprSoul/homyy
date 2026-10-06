@echo off
rem Оновити й перезапустити Хомі подвійним кліком (без налаштувань PowerShell).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-homyy.ps1"
pause
