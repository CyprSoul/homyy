from datetime import date

from agent.text import (clean_for_speech, collapse, date_diff, extract_prompt, is_noise, is_stop,
                        is_wake, split_sentences)
from agent.config import REPO_DIR


def test_collapse():
    assert collapse("Хоооуммміііі!") == "хоумі"


def test_wake_long_only():
    assert is_wake("Хоооумміііі", 1.4, 1.0, 3)
    assert is_wake("Хомі.", 1.2, 1.0, 3)
    assert is_wake("Homie", 1.3, 1.0, 3)
    assert not is_wake("Хомі", 0.4, 1.0, 3)                       # звичайне коротке
    assert not is_wake("Хомі, яка зараз погода в Києві", 2.0, 1.0, 3)  # речення, а не виклик
    assert not is_wake("Хочу", 1.5, 1.0, 3)


def test_prompt_extracted_from_repo():
    p = extract_prompt((REPO_DIR / "prompts" / "homyy-system-prompt.md").read_text(encoding="utf-8"))
    assert p.startswith("Ти — Хомі") and "{{CURRENT_DATE}}" in p and "```" not in p


def test_clean_for_speech():
    assert clean_for_speech("**Привіт**! 😊 Дивись [тут](https://x.com)") == "Привіт ! Дивись тут"


def test_split_sentences():
    s = split_sentences("Так. Звісно, зараз розповім детальніше про погоду в Києві на сьогодні. А ще?")
    assert s[0].startswith("Так. Звісно")
    assert len(s) == 2


def test_date_diff_matches_open_webui_case():
    d = date_diff(date(2026, 3, 18), date(2026, 10, 5))
    assert (d["years"], d["months"], d["days"]) == (0, 6, 17)


def test_date_diff_future():
    d = date_diff(date(2026, 12, 31), date(2026, 10, 5))
    assert d["direction"] == "майбутнє" and d["total_days"] == 87


def test_noise_and_stop():
    assert is_noise("Дякую за перегляд!")
    assert not is_noise("Яка погода?")
    assert is_stop("Дякую, все.")
    assert is_stop("Дякую, це все.")
    assert is_stop("Все, бувай!")
    assert not is_stop("Розкажи все про космос, будь ласка, детально")
    assert not is_stop("Дякую")


def test_greeting_by_time():
    from agent.text import greeting
    assert "ранку" in greeting("Ігор", 8)
    assert "вечір" in greeting("Ігор", 20).lower()
    assert "Ігор" in greeting("Ігор", 2, pick=1)


def test_pause_phrase():
    from agent.text import is_pause
    assert is_pause("Хомі, не слухай поки що")
    assert not is_pause("Постав музику на паузу")


def test_new_topic():
    from agent.text import is_new_topic
    assert is_new_topic("Давай нова тема") and is_new_topic("Змінимо тему.") and is_new_topic("Забудь розмову")
    assert not is_new_topic("Розкажи про нову тему в моді цієї осені та що зараз носять у Європі")


def test_looks_ukrainian_catches_wrong_language():
    from agent.text import looks_ukrainian
    assert not looks_ukrainian("Ты тут, приведя кто расправы.")
    assert not looks_ukrainian("Uh none of mine no.")
    assert not looks_ukrainian("Привет.")
    assert not looks_ukrainian("Расскажи про космос.")
    assert looks_ukrainian("Розкажи про космос, я хочу послухати.")
    assert looks_ukrainian("Привіт, як твої справи? Я сьогодні вдома.")
    assert looks_ukrainian("Яка привида, я кажу, як справи в тебе?")
    assert looks_ukrainian("")


def test_unfinished_phrase_waits_longer():
    from agent.text import unfinished
    assert unfinished("Я займаюся тим, що") == 2.5
    assert unfinished("Розкажи про") == 2.5
    assert unfinished("Котра година") == 0.6
    assert unfinished("Привіт, як справи?") == 0.0
    assert unfinished("Я хочу.") == 2.5                  # розпізнавач поставив крапку на паузі
    assert unfinished("Нагадай.") == 2.5
    assert unfinished("Пошукай сферу і покажи.") == 0.0
    assert unfinished("Я хочу м.") == 2.5
    assert unfinished("Привіт.") == 0.7
    assert unfinished("Яка завтра погода в Києві.") == 0.0


def test_interrupt_request():
    from agent.text import interrupt_request
    assert interrupt_request("Стоп, стоп. А яка погода завтра?", "Сьогодні сонячно") == "а яка погода завтра"
    assert interrupt_request("Стоп!", "Сьогодні сонячно") == ""
    assert interrupt_request("Хомі, почекай", "Сьогодні сонячно") == ""
    assert interrupt_request("сьогодні сонячно і тепло", "Сьогодні сонячно і тепло") is None
    assert interrupt_request("Привіт, я Хомі", "Привіт, я Хомі") is None     # її власний голос


def test_split_wake():
    from agent.text import split_wake
    assert split_wake("Хомі, яка завтра погода?") == "яка завтра погода?"
    assert split_wake("Хооміі. Увімкни музику") == "Увімкни музику"
    assert split_wake("Ну Хомі, привіт") == "привіт"
    assert split_wake("Хомі.") == ""
    assert split_wake("Яка погода?") is None
    assert split_wake("Я вдома") is None


def test_media_intent():
    from agent.text import media_intent
    assert media_intent("Схоже, постав на паузу.") == "pause"
    assert media_intent("Хомі, постав на паузу") == "pause"
    assert media_intent("Продовжуй") == "play"
    assert media_intent("Наступна пісня") == "next"
    assert media_intent("Зроби гучніше, будь ласка") == "volume_up"
    assert media_intent("тихіше") == "volume_down"
    assert media_intent("Нагадай мені наступного тижня про лікаря") is None
    assert media_intent("Розкажи, чому музика на паузі буває корисною для концентрації уваги") is None


def test_claims_action():
    from agent.text import claims_action
    assert claims_action("Зрозуміла, Ігорю. Музику поставила на паузу.")
    assert claims_action("Відкриваю YouTube!")
    assert not claims_action("Космос — це неймовірно цікаво.")


def test_click_intent_and_promises():
    from agent.text import claims_action, click_intent
    assert click_intent("Натисни на igorko2018") == "igorko2018"
    assert click_intent("Хомі, клікни «I don't agree».") == "I don't agree"
    assert click_intent("Натисни кнопку Грати") == "Грати"
    assert click_intent("Розкажи, як натиснути на кнопку") is None
    assert claims_action("Я зрозуміла, Ігорю. Зараз натисну «I don't agree».")


def test_window_and_selection_intents():
    from agent.text import wants_selection, window_intent
    assert window_intent("Хомі, згорни термінал") == ("minimize", "термінал")
    assert window_intent("Згорни все") == ("minimize_all", "")
    assert window_intent("Розгорни ютуб") == ("maximize", "ютуб")
    assert window_intent("Перейди в дискорд") == ("focus", "дискорд")
    assert window_intent("Розкажи, як згорнути вікно в Windows швидко і без мишки") is None
    assert wants_selection("Я виділив текст, переклади")
    assert not wants_selection("Переклади: я втомився")


def test_folder_intent():
    from agent.text import folder_intent
    assert folder_intent("Хомі, що в папці Games на робочому столі?") == ("list_folder", "games")
    assert folder_intent("Що лежить у папці завантаження") == ("list_folder", "завантаження")
    assert folder_intent("Відкрий папку Games") == ("open_folder", "games")
    assert folder_intent("Що таке папка?") is None


def test_dialog_fixes():
    from agent.text import fix_command, foreign_speech, promises_more
    assert fix_command("Пошукаю в інтернеті сферу") == "Пошукай в інтернеті сферу"
    assert fix_command("Привіт") == "Привіт"
    her = ("Ти хочеш створити щось на кшталт інтерактивного веб-об'єкта. Так, це дуже актуально, "
           "і тобі варто дивитися в бік Three.js.")
    assert foreign_speech("Так, дякую. Просто відкрий і покажи мені це.", her)   # ти, а не її луна
    assert not foreign_speech("тобі варто дивитися в бік", her)
    assert promises_more("Це круто. Хочеш, я знайду конкретні приклади коду?")
    assert promises_more("Я можу пошукати для тебе конкретні назви програм.")


def test_is_repeat():
    from agent.text import is_repeat
    assert is_repeat("Що?") and is_repeat("Повтори, будь ласка") and is_repeat("Не почув")
    assert not is_repeat("Що таке самвидав?")
