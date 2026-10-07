# Автооновлення Вікіпедії для Хомі: раз на тиждень (неділя 12:00) перевіряє, чи вийшла новіша,
# і якщо так — качає й підміняє. Якщо ПК був вимкнений — зробить, щойно ввімкнеш.
# Запуск один раз: powershell -ExecutionPolicy Bypass -File .\scripts\schedule-kiwix-update.ps1
# Прибрати:        Unregister-ScheduledTask -TaskName "Homyy Kiwix update" -Confirm:$false
# Журнал оновлень: C:\homyy\kiwix\update.log
$script = Join-Path $PSScriptRoot "install-kiwix.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Quiet"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 12:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName "Homyy Kiwix update" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Оновлення офлайн-Вікіпедії для Хомі" -Force | Out-Null
Write-Host "Готово: Вікіпедія перевірятиме оновлення щонеділі о 12:00 (журнал C:\homyy\kiwix\update.log)."
