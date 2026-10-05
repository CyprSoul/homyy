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
