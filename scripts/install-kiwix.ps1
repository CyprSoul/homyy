# Українська Вікіпедія офлайн для Хомі (Kiwix): качає свіжий ZIM (~5–7 ГБ, без картинок) і запускає сервер.
# Запуск: .\scripts\install-kiwix.ps1        (повторний запуск — докачає/оновить)
$ErrorActionPreference = "Stop"
if ($args -contains "-Quiet") { Start-Transcript -Append -Path "C:\homyy\kiwix\update.log" | Out-Null }
$dir = "C:\homyy\kiwix"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$base = "https://download.kiwix.org/zim/wikipedia/"
Write-Host "Шукаю найсвіжішу українську Вікіпедію…"
$list = (Invoke-WebRequest -UseBasicParsing $base).Content
$files = [regex]::Matches($list, 'wikipedia_uk_all_nopic_\d{4}-\d{2}\.zim') | ForEach-Object { $_.Value } | Sort-Object -Unique
if (-not $files) { throw "Не знайшла файлів wikipedia_uk_all_nopic на $base" }
$file = $files[-1]
$path = Join-Path $dir $file
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "config\kiwix")
$env:KIWIX_DIR = $dir
$ErrorActionPreference = "Continue"; docker info *> $null; $ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { throw "Docker не запущений — запусти Docker Desktop і повтори." }
if (Test-Path $path) {
    Write-Host "Вже найсвіжіша: $file — нічого качати."
    docker compose up -d                  # переконатися, що сервер працює
} else {
    Write-Host "Качаю $file у $dir (можна перервати й запустити знову — докачає)…"
    curl.exe -L -C - -o "$path.part" ($base + $file)
    if ($LASTEXITCODE -ne 0) { throw "Завантаження перервалось — запусти скрипт ще раз, докачає." }
    Move-Item -Force "$path.part" $path
    docker compose down                   # сервер відпускає старий файл
    Get-ChildItem $dir -Filter "wikipedia_uk_all_nopic_*.zim" | Where-Object { $_.Name -ne $file } | Remove-Item -Force
    docker compose up -d --force-recreate # стартує вже з новим файлом
    Write-Host "Оновлено до $file."
}
Write-Host ""
Write-Host "Готово. Перевір: http://127.0.0.1:8090 — має відкритися Вікіпедія."
Write-Host "Далі в agent\config.toml додай:"
Write-Host "  [kiwix]"
Write-Host '  url = "http://127.0.0.1:8090"'
