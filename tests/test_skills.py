from agent.skills import SkillBook


def test_learns_after_two_successes(tmp_path):
    book = SkillBook(tmp_path / "s.json")
    calls = [{"name": "open_app", "arguments": {"name": "discord"}}]
    assert not book.observe("Хомі, відкрий дискорд", calls, ["Відкрила Discord."])
    assert book.match("відкрий дискорд") is None                     # раз — ще не навичка
    assert book.observe("Відкрий, будь ласка, дискорд", calls, ["Відкрила Discord."])
    skill = SkillBook(tmp_path / "s.json").match("Хомі, відкрий дискорд")   # пам'ятає й після перезапуску
    assert skill and skill["calls"] == calls
    assert book.match("відкрий телеграм") is None


def test_dangerous_or_failed_is_not_learned(tmp_path):
    book = SkillBook(tmp_path / "s.json")
    kill = [{"name": "close_app", "arguments": {"name": "discord", "confirmed": True}}]
    for _ in range(3):
        assert not book.observe("закрий дискорд", kill, ["Закрила: Discord.exe."])
    bad = [{"name": "open_app", "arguments": {"name": "фотошоп"}}]
    for _ in range(3):
        assert not book.observe("відкрий фотошоп", bad, ["Не знайшла програми «фотошоп»."])
    assert book.learned() == []


def test_forget(tmp_path):
    book = SkillBook(tmp_path / "s.json")
    calls = [{"name": "window", "arguments": {"action": "minimize_all"}}]
    book.observe("прибери все з екрана", calls, ["Згорнула все."])
    book.observe("прибери все з екрана", calls, ["Згорнула все."])
    assert book.match("прибери все з екрана")
    assert book.forget("забудь, як прибери все з екрана")
    assert book.match("прибери все з екрана") is None
