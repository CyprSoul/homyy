# Перестворює контейнер Open WebUI з потрібними змінними середовища.
# Дані (чати, Хомі, пам'ять) зберігаються в томі open-webui і не губляться.
docker stop open-webui
docker rm open-webui
docker run -d -p 3000:8080 --add-host=host.docker.internal:host-gateway `
  -v open-webui:/app/backend/data `
  -e ENABLE_MEMORY_BACKGROUND_REVIEW=True `
  -e MEMORIES_REVIEW_INTERVAL_TURNS=3 `
  --name open-webui --restart always ghcr.io/open-webui/open-webui:main
