from agent.diary import Diary, dialog_text


def test_diary_prompt_and_search(tmp_path):
    d = Diary(tmp_path / "d.jsonl")
    d.add("NONE")                                             # порожня розмова не пишеться
    d.add("Ігор хоче почати тренування тричі на тиждень, домовились про план на понеділок.", when=1.7e9)
    d.add("Говорили про сферу на Three.js для іконки Хомі.", when=1.7e9 + 100)
    block = d.prompt_block()
    assert "ОСТАННІ НАШІ РОЗМОВИ" in block and "Three.js" in block and "NONE" not in block
    assert "тренування" in d.search("що я казав про тренування?")[0]
    assert d.search("погода") == []


def test_summarize_writes_diary(monkeypatch, tmp_path):
    from agent.brain import Brain
    b = Brain({"user": {"name": "Ігор"}, "ollama": {"url": "http://x", "model": "m"}, "apps": {},
               "search": {"url": "http://x"}, "openwebui": {}})
    b.diary = Diary(tmp_path / "d.jsonl")
    reply = {"message": {"content": "Ігор питав про самиздат і просив коротших відповідей."}}
    monkeypatch.setattr("agent.brain.requests.post", lambda *a, **k: type("R", (), {
        "raise_for_status": lambda self: None, "json": lambda self: reply})())
    talk = [{"role": "user", "content": "Що таке самвидав?"}, {"role": "assistant", "content": "Це…"},
            {"role": "user", "content": "Коротше"}, {"role": "assistant", "content": "Добре."}]
    assert b.summarize(talk) == "Ігор питав про самвидав і просив коротших відповідей."
    assert "самвидав" in b.diary.prompt_block()
    assert b.summarize(talk[:2]) is None                     # одне питання — не розмова
    assert "Ігор: Що таке самвидав?" in dialog_text(talk)


def test_diary_understands_yesterday_and_last_time(tmp_path):
    import time
    from datetime import datetime, timedelta
    d = Diary(tmp_path / "diary.jsonl")
    noon = datetime.now().replace(hour=12)
    d.add("Говорили про тренування вдома без гантелей.", when=(noon - timedelta(days=1)).timestamp())
    d.add("Обговорили поїздку до Львова.", when=(noon - timedelta(days=3)).timestamp())
    d.add("Сьогодні слухали музику.", when=time.time())
    yesterday = d.search("Ти пам'ятаєш, про що ми з тобою вчора говорили?")
    assert len(yesterday) == 1 and "тренування" in yesterday[0]          # раніше «вчора» шукалось як слово
    assert "Львова" in d.search("що ми вирішили про Львів")[0]
    assert len(d.search("про що ми говорили минулого разу")) == 3


def test_recall_question_is_a_quick_command():
    from agent.router import route
    r = route("Ти пам'ятаєш, про що ми з тобою вчора говорили?")
    assert r.tool == "recall" and "щоденнику" in r.summarize
    assert route("Що ми вирішили щодо тренувань?").tool == "recall"
    reminder = route("Нагадай мені через десять хвилин випити воду")
    assert reminder is None or reminder.tool != "recall"
