# Записує твоє «Хооміі» й навчає персональний детектор. Перед запуском вимкни Хомі.
Set-Location (Split-Path -Parent $PSScriptRoot)
.\.venv\Scripts\python -m agent.record_wake @args
