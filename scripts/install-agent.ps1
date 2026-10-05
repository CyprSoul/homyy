# Встановлює голосову Хомі: віртуальне середовище Python 3.11 і бібліотеки.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path .venv)) { py -3.11 -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r agent\requirements.txt
if (-not (Test-Path agent\config.toml)) { Copy-Item agent\config.example.toml agent\config.toml }
Write-Host "Готово! Налаштування: agent\config.toml. Запуск: scripts\run-agent.ps1"
