# Хомі без вікна терміналу: ярлик в автозапуску Windows і на Робочому столі.
# Журнал — правий клік по сфері → «Відкрити журнал». Прибрати з автозапуску: Win+R → shell:startup → видалити «Хомі».
$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Startup"), [Environment]::GetFolderPath("Desktop"))) {
  $s = $shell.CreateShortcut((Join-Path $dir "Хомі.lnk"))
  $s.TargetPath = $pythonw
  $s.Arguments = "-m agent"
  $s.WorkingDirectory = $repo
  $s.Description = "Хомі — голосова помічниця"
  $s.Save()
}
Write-Host "Готово! Хомі запускатиметься разом із Windows без вікна терміналу. Ярлик «Хомі» є й на Робочому столі."
