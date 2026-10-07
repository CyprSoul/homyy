# Українська Вікіпедія офлайн для Хомі (Kiwix): качає свіжий ZIM (~5–7 ГБ, без картинок) і запускає сервер.
# Запуск: .\scripts\install-kiwix.ps1        (повторний запуск — докачає/оновить)
$ErrorActionPreference = "Stop"
$dir = "C:\homyy\kiwix"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$base = "https://download.kiwix.org/zim/wikipedia/"
Write-Host "Шукаю найсвіжішу українську Вікіпедію…"
$list = (Invoke-WebRequest -UseBasicParsing $base).Content
$files = [regex]::Matches($list, 'wikipedia_uk_all_nopic_\d{4}-\d{2}\.zim') | ForEach-Object { $_.Value } | Sort-Object -Unique
if (-not $files) { throw "Не знайшла файлів wikipedia_uk_all_nopic на $base" }
$file = $files[-1]
$path = Join-Path $dir $file
Write-Host "Качаю $file у $dir (можна перервати й запустити знову — докачає)…"
curl.exe -L -C - -o $path ($base + $file)
Get-ChildItem $dir -Filter "wikipedia_uk_all_nopic_*.zim" | Where-Object { $_.Name -ne $file } | Remove-Item -Force
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "config\kiwix")
$env:KIWIX_DIR = $dir
docker compose up -d
Write-Host ""
Write-Host "Готово. Перевір: http://127.0.0.1:8090 — має відкритися Вікіпедія."
Write-Host "Далі в agent\config.toml додай:"
Write-Host "  [kiwix]"
Write-Host '  url = "http://127.0.0.1:8090"'
