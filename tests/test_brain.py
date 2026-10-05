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
    tool_msg = seen[1][-1]
    assert tool_msg["role"] == "tool" and '"days": 17' in tool_msg["content"]
    assert tool_msg["content"].endswith(STYLE_REMINDER)
    assert b.history[-1] == {"role": "assistant", "content": "Тимофію шість місяців і сімнадцять днів."}
