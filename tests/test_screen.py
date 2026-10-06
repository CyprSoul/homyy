from agent import screen


WORDS = [("Хто", (500, 160, 60, 30)), ("грає?", (565, 160, 80, 30)),
         ("igorko2018", (330, 320, 110, 22)), ("_igosha_", (345, 345, 80, 16)),
         ("Пропонувати", (140, 385, 120, 18)), ("вибір", (265, 385, 50, 18))]


def test_finds_spoken_name_written_in_latin():
    label, (x, y), score = screen.best_match("Ігорку 2018", WORDS)
    assert label == "igorko2018" and score >= 0.75
    assert (x, y) == (385, 331)


def test_multiword_and_missing():
    assert screen.best_match("Хто грає", WORDS)[0] == "Хто грає?"
    assert screen.best_match("Видалити акаунт", WORDS)[2] < 0.75


def test_risky_click_needs_yes(monkeypatch):
    from agent.tools import Tools
    t = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    clicks = []
    monkeypatch.setattr(screen, "available", lambda: True)
    monkeypatch.setattr(screen, "screen_words", lambda: [("Видалити", (10, 10, 50, 20))])
    monkeypatch.setattr(screen, "click", lambda x, y: clicks.append((x, y)))
    assert "ПІДТВЕРДЖЕННЯ" in t.call("click_on_screen", {"text": "видалити"})
    assert clicks == []
    monkeypatch.setattr(screen, "screen_words", lambda: WORDS)
    assert t.call("click_on_screen", {"text": "Ігорку 2018"}) == "Натиснула «igorko2018»."
    assert clicks == [(385, 331)]
