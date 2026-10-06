# Оновлює й перезапускає Хомі однією командою:  .\scripts\restart-homyy.ps1
# Закриває стару Хомі, бере свіжий код і запускає Хомі без вікна терміналу (Gemma лишається в пам'яті).
Set-Location (Split-Path -Parent $PSScriptRoot)
# Хомі й її сфера (окремий процес) — усе, що запущене з .venv цієї папки
$venv = (Resolve-Path ".\.venv").Path
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Where-Object { $_.CommandLine -match '-m agent' -or ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, 'OrdinalIgnoreCase')) } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500
git pull
Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "-m agent" -WorkingDirectory (Get-Location)
Write-Host "Хомі перезапущена. Дивитися, що вона пише: .\scripts\watch-log.cmd (або Get-Content agent\homyy.log -Wait -Tail 20)"
