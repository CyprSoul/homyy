from pathlib import Path

from agent.pctools import apply_plan, category, downloads_plan
from agent.text import is_yes
from agent.tools import Tools

CFG = {"apps": {}, "search": {"url": "http://x"}, "openwebui": {}}


def test_is_yes():
    assert is_yes("Так") and is_yes("так, давай") and is_yes("Ага.")
    assert not is_yes("Ні") and not is_yes("не треба") and not is_yes("Так, але спершу розкажи мені про погоду завтра")


def test_confirmation_is_enforced_by_code():
    t = Tools(CFG)
    t.last_user_text = "Вимкни комп'ютер через годину"
    # модель «одразу» ставить confirmed=true — код однаково спершу перепитує
    assert "ПОТРІБНЕ ПІДТВЕРДЖЕННЯ" in t.call("shutdown_timer", {"minutes": 60, "confirmed": True})
    t.last_user_text = "ні"
    assert "ПОТРІБНЕ ПІДТВЕРДЖЕННЯ" in t.call("shutdown_timer", {"minutes": 60, "confirmed": True})
    t.call("shutdown_timer", {"minutes": 60})
    t.last_user_text = "так"
    assert "вимкнеться через 60 хв" in t.call("shutdown_timer", {"minutes": 60, "confirmed": True})
    # інші параметри, ніж ті, що підтверджували, — знову перепитати
    t.call("shutdown_timer", {"minutes": 60})
    t.last_user_text = "так"
    assert "ПОТРІБНЕ ПІДТВЕРДЖЕННЯ" in t.call("shutdown_timer", {"minutes": 5, "confirmed": True})


def test_downloads_plan_moves_without_overwrite(tmp_path: Path):
    for n in ["a.jpg", "b.pdf", "c.zip", "d.xyz", "e.crdownload"]:
        (tmp_path / n).write_text("x")
    (tmp_path / "Картинки").mkdir()
    (tmp_path / "Картинки" / "a.jpg").write_text("old")
    plan = downloads_plan(tmp_path)
    assert {k: len(v) for k, v in plan.items()} == {"Картинки": 1, "Документи": 1, "Архіви": 1, "Інше": 1}
    assert apply_plan(tmp_path, plan) == 4
    assert (tmp_path / "Картинки" / "a (1).jpg").exists() and (tmp_path / "Картинки" / "a.jpg").read_text() == "old"
    assert (tmp_path / "e.crdownload").exists()
    assert category(Path("x.MP4")) == "Відео"


def test_reminder_fires():
    import time
    t = Tools(CFG)
    said = []
    t.on_reminder = said.append
    assert "Таймер поставлено" in t.call("set_reminder", {"minutes": 0.001, "text": "випити води"})
    time.sleep(0.5)
    assert said == ["Нагадую: випити води."]


def test_yes_after_question_runs_tool(monkeypatch):
    from agent.text import is_no, is_yes
    from agent.tools import Tools
    t = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    monkeypatch.setattr(t, "_find_processes", lambda name: ["Discord.exe"])
    monkeypatch.setattr("agent.pctools.subprocess.run", lambda *a, **k: None)
    monkeypatch.setattr("agent.pctools.time.sleep", lambda s: None)
    t.last_user_text = "Хомі, закрий дискорд"
    assert t.call("close_app", {"name": "discord"}).startswith("ПОТРІБНЕ ПІДТВЕРДЖЕННЯ")
    assert t.awaiting == ("close_app", {"name": "discord"})
    assert is_yes("Хо мені да?") and is_yes("Так, закривай") and not is_yes("Ні, не треба")
    assert is_no("ні, не треба")
    t.last_user_text = "Хо мені да?"
    assert t.call("close_app", {"name": "discord", "confirmed": True}).startswith("Закрила")
    assert t.awaiting is None


def test_confirmed_without_yes_is_refused():
    from agent.tools import Tools
    t = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    t.last_user_text = "Закрий дискорд"                 # модель сама поставила confirmed=true
    assert t._needs_yes("close_app", "discord", True, "Закрити") is not None


def test_list_folder(tmp_path, monkeypatch):
    import agent.pctools as pc
    from agent.tools import Tools
    games = tmp_path / "Desktop" / "Games"
    (games / "World of Tanks").mkdir(parents=True)
    (games / "cs2.lnk").write_text("x")
    monkeypatch.setattr(pc, "HOME", tmp_path)
    monkeypatch.setattr(pc, "SEARCH_DIRS", ["Desktop"])
    t = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    out = t.call("list_folder", {"name": "гейм"})
    assert "Не знайшла" in out or "World of Tanks" in out
    out = t.call("list_folder", {"name": "Games"})
    assert "World of Tanks" in out and "cs2.lnk" in out
