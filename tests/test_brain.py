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
    # «done» — що справді зробив код (тут нічого: date_difference лише рахує) — для правдивого щоденника
    assert b.history[-1] == {"role": "assistant", "content": "Тимофію шість місяців і сімнадцять днів.", "done": []}


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
    # про дію каже квитанція інструмента, а не переказ моделі
    assert b.ask("Постав, будь ласка, музику на паузу, бо дзвонять") == "Поставила на паузу «Пісня»."
    assert called == [("media", {"action": "pause"})]


def test_receipt_replaces_models_retelling_and_keeps_the_rest(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "open_app", "arguments": {"name": "Discord"}}}]},
        {"content": "Відкрила Дискорд для тебе! Пограєш із друзями?"},
    ])
    monkeypatch.setattr(b, "_chat", lambda m: next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: "Відкрила Discord.")
    assert b.ask("Запусти дискорд") == "Відкрила Discord. Пограєш із друзями?"


def test_failed_action_is_not_retold_as_done(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "open_app", "arguments": {"name": "Фотошоп"}}}]},
        {"content": "Відкрила Фотошоп."},                                         # модель «не помітила» невдачі
    ])
    monkeypatch.setattr(b, "_chat", lambda m: next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: "Не знайшла програми «Фотошоп» серед встановлених.")
    assert b.ask("Відкрий фотошоп") == "Не знайшла програми «Фотошоп» серед встановлених."


def test_short_done_claim_without_tool_is_checked(monkeypatch):
    """Так було в наборі перевірок: «зніме з паузи» → «Продовжую.», хоча нічого не виконано."""
    b = Brain(CFG)
    replies = iter([
        {"content": "Продовжую."},                                                # бреше
        {"content": "", "tool_calls": [{"function": {"name": "media", "arguments": {"action": "play"}}}]},
        {"content": "Продовжила."},
    ])
    seen = []
    monkeypatch.setattr(b, "_chat", lambda m: seen.append(list(m)) or next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: "Продовжила «Пісня».")
    assert b.ask("Можна далі") == "Продовжила «Пісня»."
    assert "Системна перевірка" in seen[1][-1]["content"]


def test_receipt_is_spoken_before_model_continues(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "set_reminder", "arguments": {"minutes": 1}}}]},
        {"content": "Нагадаю вчасно. Не забудь налити повну пляшку."},
    ])
    said = []

    def fake_chat(messages, on_delta=None, cancel=None):
        reply = next(replies)
        if on_delta and reply.get("content"):
            on_delta(reply["content"] + " ")              # як потік: текст іде шматками в голос
        return reply
    monkeypatch.setattr(b, "_chat", fake_chat)
    monkeypatch.setattr(b.tools, "call", lambda n, a: "Таймер поставлено: о 18:30 нагадаю — вода.")
    b.ask("Нагадай через хвилину про воду", on_sentence=said.append)
    assert said[0] == "Таймер поставлено: о 18:30 нагадаю — вода."       # квитанція — першою
    assert "Не забудь налити повну пляшку." in said


def test_false_work_claim_is_not_spoken_when_nothing_is_being_written(monkeypatch):
    """Так було: «я ще пишу сторінку», хоча ніхто нічого не запускав, — і Ігор чекав на сторінку, якої нема."""
    from agent.brain import IDLE_ANSWER
    b = Brain(CFG)
    replies = iter([
        {"content": "Я справді ще не закінчила її писати, тому відкрити поки нічого не можу."},
        {"content": "Так, я ще пишу код сторінки, зачекай."},                      # навіть після перевірки
    ])
    seen = []
    monkeypatch.setattr(b, "_chat", lambda m: seen.append(list(m)) or next(replies))
    assert b.ask("Хочу подивитися на сторінку трекера.") == IDLE_ANSWER
    check = seen[1][-1]["content"]
    assert "Системна перевірка" in check and "open_page" in check            # їй нагадали, що робити насправді


def test_work_claim_is_allowed_while_a_page_is_really_being_written(monkeypatch):
    import types
    b = Brain(CFG)
    b.tools._page_builder = types.SimpleNamespace(busy="тренування", last=None, names=lambda: [],
                                                  status=lambda: "пишу, минуло 1:05")
    monkeypatch.setattr(b, "_chat", lambda m: {"content": "Я ще пишу сторінку, скоро буде готово."})
    assert b.ask("Як там сторінка?") == "Я ще пишу сторінку, скоро буде готово."


def test_background_status_is_truthful_before_any_page_was_made_in_this_run(monkeypatch, tmp_path):
    from agent import builder
    from agent.tools import Tools
    monkeypatch.setattr(builder, "pages_dir", lambda: tmp_path)
    (tmp_path / "тренування.html").write_text("<html></html>", encoding="utf-8")
    status = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}}).background_status()
    assert "НЕ пишеш" in status and "тренування" in status               # після перезапуску довідка не порожня


def test_invented_numbers_after_search_are_not_spoken(monkeypatch):
    """Так було в наборі перевірок: пошук погоди не приніс, а відповідь — «12–15 градусів»."""
    from agent.brain import NO_DATA_ANSWER
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "погода Київ"}}}]},
        {"content": "Завтра в Києві хмарно, від дванадцяти до п'ятнадцяти градусів."},      # вигадка
        {"content": "Завтра в Києві до 15 градусів, як завжди."},                              # і вдруге
    ])
    seen, said = [], []

    def fake_chat(messages, on_delta=None, cancel=None):
        seen.append(list(messages))
        reply = next(replies)
        if on_delta and reply.get("content"):
            on_delta(reply["content"] + " ")
        return reply
    monkeypatch.setattr(b, "_chat", fake_chat)
    monkeypatch.setattr(b.tools, "call", lambda n, a: "[1] Київ — столиця України.\nДжерело: wiki")
    answer = b.ask("Яка завтра погода в Києві?", on_sentence=said.append)
    assert "Системна перевірка" in seen[2][-1]["content"] and "12" in seen[2][-1]["content"]
    assert not any("градус" in s for s in said)                       # вигадані числа так і не прозвучали
    assert answer.endswith(NO_DATA_ANSWER)


def test_numbers_from_search_results_pass(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "web_search", "arguments": {"query": "погода Львів"}}}]},
        {"content": "Завтра у Львові чотирнадцять градусів і дощ увечері."},
    ])
    monkeypatch.setattr(b, "_chat", lambda m: next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: "Львів, завтра: +14°C, хмарно, увечері дощ.")
    assert b.ask("Яка завтра погода у Львові?") == "Завтра у Львові чотирнадцять градусів і дощ увечері."


def test_fact_about_me_is_remembered_even_if_model_does_not(monkeypatch):
    b = Brain(CFG)
    b.remember_in_background = False
    called = []
    monkeypatch.setattr(b, "_chat", lambda m: {"content": "Класно! У які ігри граєш?"})
    monkeypatch.setattr(b.tools, "call", lambda n, a: called.append((n, a)) or "Записано в пам'ять.")
    assert b.ask("Я люблю грати комп'ютерні ігри.") == "Класно! У які ігри граєш?"
    assert called == [("remember", {"fact": "Ігор про себе: «Я люблю грати комп'ютерні ігри.»"})]
    assert b.auto_memories == ["Ігор про себе: «Я люблю грати комп'ютерні ігри.»"]


def test_remembered_claim_is_true_when_code_saved_the_fact(monkeypatch):
    """Так було: «Я не люблю каву» → модель «Запам'ятала.» без інструмента → перевірка → «Не зрозуміла…»."""
    b = Brain(CFG)
    b.remember_in_background = False
    called, seen = [], []
    monkeypatch.setattr(b, "_chat", lambda m: seen.append(list(m)) or {"content": "Запам'ятала! А чай любиш?"})
    monkeypatch.setattr(b.tools, "call", lambda n, a: called.append(n) or "Записано в пам'ять.")
    assert b.ask("Я не люблю каву.") == "Запам'ятала! А чай любиш?"
    assert called == ["remember"] and len(seen) == 1                     # без перевірки й без другого запису
    assert "вже записано в пам'ять" in seen[0][-1]["content"]


def test_will_remind_is_true_when_reminder_exists(monkeypatch):
    """Так було в наборі перевірок: «Ти не забудеш нагадати?» → «Нагадаю…» → «брехня» → «Не зрозуміла…»."""
    b = Brain(CFG)
    b.tools.jobs.add_reminder(30, "випити воду")
    seen = []
    monkeypatch.setattr(b, "_chat", lambda m: seen.append(1) or {"content": "Не забуду, нагадаю про воду вчасно."})
    assert b.ask("Ти не забудеш нагадати мені про воду?") == "Не забуду, нагадаю про воду вчасно."
    assert len(seen) == 1                                       # без перевірки «а де ж дія?»


def test_will_remind_without_reminder_is_checked(monkeypatch):
    b = Brain(CFG)
    seen = []
    replies = iter([{"content": "Звісно, нагадаю!"},
                    {"content": "", "tool_calls": [{"function": {"name": "set_reminder",
                                                                 "arguments": {"minutes": 10, "text": "вода"}}}]},
                    {"content": "Поставила."}])
    monkeypatch.setattr(b, "_chat", lambda m: seen.append(1) or next(replies))
    assert b.ask("Нагадаєш мені через десять хвилин про воду?").startswith("Таймер поставлено")
    assert len(seen) == 3                                       # нагадування не було — «нагадаю» перевірили


def test_request_is_not_mistaken_for_a_fact(monkeypatch):
    b = Brain(CFG)
    b.remember_in_background = False
    called = []
    monkeypatch.setattr(b, "_chat", lambda m: {"content": "Добре."})
    monkeypatch.setattr(b.tools, "call", lambda n, a: called.append(n) or "")
    b.ask("Я хочу, щоб ти розповіла про космос.")
    b.ask("Ти любиш осінь?")
    assert "remember" not in called


def test_promise_without_result_is_followed_up(monkeypatch):
    b = Brain(CFG)
    replies = iter([
        {"content": "", "tool_calls": [{"function": {"name": "window", "arguments": {"action": "minimize_all"}}}]},
        {"content": "Я згорнула всі вікна. Зараз я загляну в папку Games і скажу тобі, що там є."},
        {"content": "", "tool_calls": [{"function": {"name": "list_folder", "arguments": {"name": "Games"}}}]},
        {"content": "У папці Games: World of Tanks і CS2."},
    ])
    monkeypatch.setattr(b, "_chat", lambda m: next(replies))
    monkeypatch.setattr(b.tools, "call", lambda n, a: "Згорнула всі вікна." if n == "window" else
                        "У Робочий стіл\\Games: файлів 2. Файли: World of Tanks.lnk, CS2.lnk")
    # «згорнула» каже квитанція (і вдруге модель це не повторює), вміст папки переказує модель
    assert (b.ask("Згорни все і подивись, що в папці Games")
            == "Згорнула всі вікна. У папці Games: World of Tanks і CS2.")


def test_deep_think_and_ukrainian_guard(monkeypatch):
    b = Brain(CFG)
    payloads = []

    def fake_post(url, timeout, json):
        payloads.append(json)
        content = "Привет, как дела?" if len(payloads) == 1 else "Привіт, усе добре. Самиздат — це цікаво."
        return type("R", (), {"status_code": 200, "raise_for_status": lambda self: None,
                              "json": lambda self: {"message": {"content": content}, "done_reason": "stop"}})()
    monkeypatch.setattr("agent.brain.requests.post", fake_post)
    monkeypatch.setattr(b, "_memories", lambda: [])
    answer = b.ask("Добре подумай і скажи, як справи")
    assert payloads[0]["think"] is True and payloads[0]["options"]["num_predict"] > 1000
    assert answer == "Привіт, усе добре. Самвидав — це цікаво."            # українською й без русизмів
    assert "українською" in payloads[1]["messages"][-1]["content"]


class _StreamResp:
    def __init__(self, chunks):
        import json as _j
        self.lines = [_j.dumps({"message": {"content": c}, "done": False}).encode() for c in chunks]
        self.lines.append(_j.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}).encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self.lines)


def test_streaming_speaks_sentences_as_they_come(monkeypatch):
    b = Brain(CFG)
    monkeypatch.setattr(b, "_memories", lambda: [])
    chunks = ["Завтра в Софії ", "сонячно. ", "Самиздат — це ", "цікаво. Хочеш, я знайду ", "ще щось?"]
    monkeypatch.setattr("agent.brain.requests.post", lambda *a, **k: _StreamResp(chunks))
    said = []
    answer = b.ask("Яка погода?", on_sentence=said.append)
    assert said[0] == "Завтра в Софії сонячно."               # перше речення — одразу, до кінця відповіді
    assert said[1] == "Самвидав — це цікаво."                 # виправлене словником
    assert all("Хочеш, я знайду" not in x for x in said[:2])   # обіцянку притримано до перевірки


def test_streaming_cancel(monkeypatch):
    from agent.brain import Cancelled
    b = Brain(CFG)
    monkeypatch.setattr(b, "_memories", lambda: [])
    monkeypatch.setattr("agent.brain.requests.post", lambda *a, **k: _StreamResp(["Раз. ", "Два. "]))
    import pytest
    with pytest.raises(Cancelled):
        b.ask("Привіт", on_sentence=lambda s: None, cancel=lambda: True)


def test_greet_in_own_words_and_not_repeating(monkeypatch, tmp_path):
    b = Brain(CFG)
    monkeypatch.setattr(b, "_memories", lambda: [])
    monkeypatch.setattr(Brain, "GREET_FILE", tmp_path / "g.json")
    sent = []
    replies = iter(["Ігоре, я прокинулась і вже тут — як твій вечір?", "Привіт-привіт! Усе завантажила, слухаю тебе."])

    def fake_post(url, timeout=None, json=None):
        sent.append(json["messages"][-1]["content"])
        return type("R", (), {"raise_for_status": lambda self: None,
                              "json": lambda self, t=next(replies): {"message": {"content": t}}})()
    monkeypatch.setattr("agent.brain.requests.post", fake_post)
    first = b.greet()
    second = b.greet()
    assert first and second and first != second
    assert first in sent[1]                                    # друге привітання знає перше і не повторює
