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
