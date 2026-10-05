# Перевіряє, чи Gemma в Ollama викликає інструменти (без Open WebUI).
$body = @{
  model = "gemma4:26b"; stream = $false; think = $false
  messages = @(@{ role = "user"; content = "Котра година?" })
  tools = @(@{ type = "function"; function = @{
    name = "current_datetime"; description = "Поточні дата й час."
    parameters = @{ type = "object"; properties = @{} } } })
} | ConvertTo-Json -Depth 10

Write-Host "Питаю Gemma «Котра година?» з інструментом current_datetime… (до хвилини)"
$r = Invoke-RestMethod -Uri http://localhost:11434/api/chat -Method Post -TimeoutSec 300 `
  -Body ([Text.Encoding]::UTF8.GetBytes($body)) -ContentType "application/json; charset=utf-8"

if ($r.message.tool_calls) {
  Write-Host "✅ Ollama викликала інструмент: $($r.message.tool_calls[0].function.name)" -ForegroundColor Green
} else {
  Write-Host "❌ Інструмент НЕ викликано. Відповідь текстом:" -ForegroundColor Red
  Write-Host $r.message.content
}
