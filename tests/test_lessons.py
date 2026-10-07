from agent.lessons import LessonBook, feedback, forget_request, taught_rule


def test_feedback_detection():
    assert feedback("Ні, не так, я мав на увазі відкрити") == "neg"
    assert feedback("А ти заїбала, блять.") == "neg"
    assert feedback("Супер, саме те") == "pos"
    assert feedback("Яка завтра погода?") is None


def test_teach_and_forget(tmp_path):
    book = LessonBook(tmp_path / "l.json")
    rule = taught_rule("Хомі, запам'ятай правило: коли я кажу ввімкни щось, вмикай рок")
    assert rule == "коли я кажу ввімкни щось, вмикай рок."
    assert book.add(rule)
    assert not book.add("Коли я кажу ввімкни щось — вмикай рок.")       # схоже — лише підсилює
    assert book.items[0]["weight"] == 2
    assert "УРОКИ" in book.prompt_block() and "рок" in book.prompt_block()
    assert forget_request("Хомі, забудь урок про рок") == "рок"
    assert book.forget("рок") == 1 and book.prompt_block() == ""


def test_brain_learns_rule_from_feedback(monkeypatch, tmp_path):
    from agent.brain import Brain
    from agent.lessons import LessonBook as LB
    b = Brain({"user": {"name": "Ігор"}, "ollama": {"url": "http://x", "model": "m"}, "apps": {},
               "search": {"url": "http://x"}, "openwebui": {}})
    b.lessons = LB(tmp_path / "l.json")
    reply = {"message": {"content": "Коли просять показати — відкривай у браузері, а не розповідай."}}
    monkeypatch.setattr("agent.brain.requests.post", lambda *a, **k: type("R", (), {
        "raise_for_status": lambda self: None, "json": lambda self: reply})())
    rule = b.learn("Пошукай сферу і покажи", "Сфера — це геометрична фігура…", "Просто відкрий і покажи!")
    assert rule and "браузері" in b.lessons.prompt_block()
    assert "браузері" in b._system_prompt()
