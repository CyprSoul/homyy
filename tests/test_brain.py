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
