"""Які інструменти показувати моделі на це питання.

Описи всіх ~35 інструментів — це ~3000 токенів, майже половина підказки: модель перечитує їх на кожен запит
(а запитів на одну відповідь буває 1–3), і серед 35 схожих їй легше помилитися з вибором. Тут — невеликий
постійний набір плюс групи, які вмикаються словами з питання (і з попередньої репліки: «так» після
«Закрити Discord?» має бачити close_app). Вмикається [ollama] tool_select = true.

Заміряно 11.10.2026 на gemma4:26b (python -m agent.eval_dialogs --tools all / --tools subset): з вибором
54 з 57 і 2.1 с на відповідь, з усіма — 55 з 57 і 1.6 с. Однаковий набір Ollama обробляє з кешу підказки,
змінний — щоразу заново, тож економія токенів не окуповується. Тому вимкнено; перевіряти знову — тим самим
набором (наприклад, з іншою моделлю).
"""
import re

# завжди: час, пошук, пам'ять, нагадування — потрібні майже в будь-якій розмові
CORE = {"current_datetime", "web_search", "wiki", "remember", "recall", "set_reminder", "list_jobs"}

GROUPS: dict[str, tuple[set[str], str]] = {
    "apps": ({"open_app", "close_app", "window", "open_folder", "list_folder", "find_file", "organize_downloads",
              "mark_game"},
             r"відкри|запуст|закри|згорн|розгорн|перейди|вікн|програм|папк|файл|завантаж|стім|steam|дискорд|discord|"
             r"телеграм|браузер|калькулятор|блокнот|ігр|гра\b|гру\b|робоч\w* стол"),
    "media": ({"media", "play_music"},
              r"музик|пісн|трек|пауз|гучн|тихіш|звук|плеєр|продовж|знім|наступн|попередн|увімкн|включ|постав|грай"),
    "web": ({"read_page", "open_website", "search_on_site"},
            r"сайт|ютуб|youtube|гугл|google|знайди|пошук|новин|відкри|покажи|погод|ціна|кошту|розетк|olx|карт|"
            r"прочитай|стаття|статт|англійськ"),
    "pages": ({"make_page", "edit_page", "open_page", "page_status"},
              r"сторінк|сайт|трекер|html|календар|програмк|напиши|зроби мені|перероби|додай|кнопк|графік"),
    "screen": ({"look_at_screen", "click_on_screen", "selected_text", "take_screenshot"},
               r"екран|натисн|клікн|кнопк|виділ|скрін|знімок|бачиш|подивись|що тут|переклади|погоджу|кук"),
    "power": ({"shutdown_timer", "cancel_shutdown", "sleep_pc", "lock_pc"},
              r"вимкн|виключ|сон|засни|спати|заблоку|комп'ютер|перезавантаж"),
    "time": ({"date_difference", "cancel_reminder"},
             r"скільки днів|до нового|дата|числ|нагад|таймер|скасуй|відміни|хвилин|годин|тижн|днів"),
    "memory": ({"forget_fact"}, r"забудь|пам'ят|викресли"),
    "personal": ({"mail_unread", "money_balance", "money_spending", "notes_search", "notes_add"},
                 r"пошт|лист|баланс|гроші|грош|витрат|картк|нотатк|obsidian"),
}
KNOWN = CORE.union(*(names for names, _ in GROUPS.values()))


def select_tools(schemas: list[dict], text: str, recent: str = "") -> list[dict]:
    """Підмножина описів для цього питання. Невідомі тут інструменти (MCP-конектори) — завжди."""
    t = f"{text} {recent}".lower().replace("’", "'")
    wanted = set(CORE)
    for names, pattern in GROUPS.values():
        if re.search(pattern, t):
            wanted |= names
    return [s for s in schemas if s["function"]["name"] in wanted or s["function"]["name"] not in KNOWN]
