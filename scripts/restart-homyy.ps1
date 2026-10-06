# Оновлює й перезапускає Хомі однією командою:  .\scripts\restart-homyy.ps1
# Закриває стару Хомі, бере свіжий код, вивантажує Gemma і запускає Хомі без вікна терміналу.
Set-Location (Split-Path -Parent $PSScriptRoot)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Where-Object { $_.CommandLine -match '-m agent' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
git pull
ollama stop gemma4:26b 2>$null
Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "-m agent" -WorkingDirectory (Get-Location)
Write-Host "Хомі перезапущена. Журнал: agent\homyy.log"
