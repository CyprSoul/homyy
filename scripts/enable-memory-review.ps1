# Вмикає фонову перевірку пам'яті Open WebUI (кожні 3 повідомлення).
# Змінна ENABLE_MEMORY_BACKGROUND_REVIEW не діє, якщо налаштування вже збережене в базі,
# тому змінюємо його прямо в базі й перезапускаємо контейнер.
docker exec open-webui python -c "import sqlite3;c=sqlite3.connect('/app/backend/data/webui.db');c.execute('update config set value=? where key=?',('true','memories.background_review.enable'));c.execute('update config set value=? where key=?',('3','memories.review_interval_turns'));c.commit();print([r for r in c.execute('select key,value from config') if r[0].startswith('memories')])"
docker restart open-webui
