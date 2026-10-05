# Додає голосову Хомі в автозапуск Windows (згорнуте вікно з журналом).
# Прибрати: Win+R → shell:startup → видалити ярлик «Хомі».
$repo = Split-Path -Parent $PSScriptRoot
$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Хомі.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = "powershell.exe"
$s.Arguments = "-WindowStyle Minimized -ExecutionPolicy Bypass -File `"$repo\scripts\run-agent.ps1`""
$s.WorkingDirectory = $repo
$s.WindowStyle = 7
$s.Save()
Write-Host "Готово! Хомі запускатиметься разом із Windows: $lnk"
