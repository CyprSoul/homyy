from agent.brain import STYLE_REMINDER, Brain

CFG = {"user": {"name": "Ігор", "name_genitive": "Ігоря"},
       "ollama": {"url": "http://x", "model": "m"}, "apps": {}, "search": {"url": "http://x"},
       "openwebui": {}}


def test_tool_loop(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "date_difference",
                                                      "arguments": {"from_date": "2026-03-18",
                                                                    "to_date": "2026-10-05"}}}]},
        {"content": "Тимофію шість місяців і сімнадцять днів."},
    ])
    seen = []

    def fake_chat(messages):
        seen.append(list(messages))
        return next(replies)

    monkeypatch.setattr(b, "_chat", fake_chat)
    assert b.ask("Скільки Тимофію?") == "Тимофію шість місяців і сімнадцять днів."
    system = seen[0][0]["content"]
    assert "помічниця Ігоря" in system and "ГОЛОСОВИЙ РЕЖИМ" in system and "{{" not in system
    assert "Службова довідка" in seen[0][-1]["content"] and "(Зараз " not in system
    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool" and '"days": 17' in tool_msg["content"]
    assert tool_msg["content"].endswith(STYLE_REMINDER)
    assert b.history[-1] == {"role": "assistant", "content": "Тимофію шість місяців і сімнадцять днів."}


def test_unasked_time_is_stripped():
    from agent.brain import strip_unasked_time
    a = "Я тут, Ігорю. Просто чекаю, коли ти щось скажеш. Зараз 23:45."
    assert strip_unasked_time("Що ти там?", a) == "Я тут, Ігорю. Просто чекаю, коли ти щось скажеш."
    assert strip_unasked_time("Котра година?", "Зараз 23:45.") == "Зараз 23:45."
    assert strip_unasked_time("Привіт", "Зараз 23:45.") == "Зараз 23:45."   # не лишаємо порожньо


def test_ollama_options_same_everywhere():
    from agent.config import ollama_options
    cfg = {"ollama": {"num_ctx": 16384, "num_thread": 8}}
    assert ollama_options(cfg) == {"num_ctx": 16384, "num_thread": 8}
    assert ollama_options(cfg, temperature=0.4)["temperature"] == 0.4
    assert ollama_options({"ollama": {}}) == {"num_ctx": 32768}


def test_fix_gender():
    from agent.brain import fix_gender
    assert fix_gender("Була радий допомогти, Ігорю!") == "Була рада допомогти, Ігорю!"
    assert fix_gender("Я радий тебе чути") == "Я рада тебе чути"
    assert fix_gender("Тимофій радий") == "Тимофій радий"


def test_fix_vocative():
    from agent.brain import fix_vocative
    user = {"name": "Ігор", "name_vocative": "Ігорю"}
    assert fix_vocative("Привіт, Ігоре! Як ти?", user) == "Привіт, Ігорю! Як ти?"
    assert fix_vocative("Ігорю, все добре", user) == "Ігорю, все добре"
    assert fix_vocative("Привіт, Ігоре!", {"name": "Ігор"}) == "Привіт, Ігоре!"


def test_claimed_action_without_tool_is_retried(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "Музику поставила на паузу."},                                     # бреше: інструмента нема
        {"content": "", "tool_calls": [{"function": {"name": "media", "arguments": {"action": "pause"}}}]},
        {"content": "Поставила на паузу."},
    ])
    called = []
    monkeypatch.setattr(b, "_chat", lambda m: next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: called.append((n, a)) or "Поставила на паузу «Пісня».")
    assert b.ask("Постав, будь ласка, музику на паузу, бо дзвонять") == "Поставила на паузу."
    assert called == [("media", {"action": "pause"})]


def test_promise_without_result_is_followed_up(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "window", "arguments": {"action": "minimize_all"}}}]},
        {"content": "Я згорнула всі вікна. Зараз я загляну в папку Games і скажу тобі, що там є."},
        {"content": "", "tool_calls": [{"function": {"name": "list_folder", "arguments": {"name": "Games"}}}]},
        {"content": "У папці Games: World of Tanks і CS2."},
    ])
    monkeypatch.setattr(b, "_chat", lambda m: next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: "ok")
    assert b.ask("Згорни все і подивись, що в папці Games") == "У папці Games: World of Tanks і CS2."
