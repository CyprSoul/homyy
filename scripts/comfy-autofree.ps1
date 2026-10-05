# Звільняє відеопам'ять ComfyUI, коли він 30 секунд нічого не малює,
# щоб Хомі (Ollama + Gemma) завжди мала місце у відеокарті.
$api = "http://127.0.0.1:8188"
$idleSince = $null
while ($true) {
  try {
    $q = Invoke-RestMethod "$api/queue" -TimeoutSec 5
    $busy = ($q.queue_running.Count + $q.queue_pending.Count) -gt 0
    if ($busy) { $idleSince = $null }
    elseif (-not $idleSince) { $idleSince = Get-Date }
    elseif (((Get-Date) - $idleSince).TotalSeconds -ge 30) {
      Invoke-RestMethod -Method Post "$api/free" -Body '{"unload_models":true,"free_memory":true}' -ContentType 'application/json' | Out-Null
      $idleSince = [datetime]::MaxValue   # уже звільнено, чекаємо наступного малювання
    }
  } catch { $idleSince = $null }          # ComfyUI вимкнений — просто чекаємо
  Start-Sleep -Seconds 10
}
