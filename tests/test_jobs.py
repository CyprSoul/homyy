import time

from agent.jobs import JobBook
from agent.router import route


def test_reminder_is_listed_cancelled_and_survives_restart(tmp_path):
    path = tmp_path / "jobs.json"
    said = []
    book = JobBook(path=path, on_due=said.append)
    book.add_reminder(30, "випити воду")
    book.add_reminder(60, "подзвонити мамі")
    assert "випити воду" in book.describe() and "подзвонити мамі" in book.describe()
    # перезапуск Хомі: нова книга з того самого файлу бачить ті самі нагадування
    again = JobBook(path=path)
    assert [j["title"] for j in again.active()] == ["випити воду", "подзвонити мамі"]
    assert [j["title"] for j in again.cancel("reminder", "воду")] == ["випити воду"]
    assert "воду" not in again.describe() and "мамі" in again.describe()


def test_reminder_fires_once(tmp_path):
    said = []
    book = JobBook(path=tmp_path / "jobs.json", on_due=said.append)
    book.add_reminder(0.001, "чай")                 # ~0.06 с
    time.sleep(0.5)
    assert [j["title"] for j in said] == ["чай"] and book.describe() == ""


def test_missed_reminders_are_reported_on_start(tmp_path):
    path = tmp_path / "jobs.json"
    book = JobBook(path=path)
    job = book.add_reminder(30, "вимкнути духовку")
    book._timers[job["id"]].cancel()
    job["due"] = time.time() - 600                  # Хомі була вимкнена, поки минав час
    book._save()
    missed = JobBook(path=path).arm_all()
    assert [j["title"] for j in missed] == ["вимкнути духовку"]


def test_shutdown_timer_is_one(tmp_path):
    book = JobBook(path=tmp_path / "jobs.json")
    book.add_shutdown(60)
    book.add_shutdown(30)
    assert book.describe().count("вимкнення") == 1
    book.cancel(kind="shutdown")
    assert book.describe() == ""


def test_jobs_quick_commands():
    assert route("Які в мене нагадування?").tool == "list_jobs"
    assert route("Хомі, що в мене заплановано?").tool == "list_jobs"
    assert route("Скасуй нагадування про воду.").args == {"query": "воду"}
    assert route("Скасуй усі нагадування").args == {"query": ""}
    assert route("Скасуй вимкнення").tool == "cancel_shutdown"
    reminder = route("Нагадай мені через хвилину про воду")
    assert reminder is None or reminder.tool not in ("list_jobs", "cancel_reminder")


def test_set_reminder_goes_to_the_book_and_status(monkeypatch):
    from agent.tools import Tools
    t = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    assert t.call("set_reminder", {"minutes": 30, "text": "вода"}).startswith("Таймер поставлено")
    assert "нагадування о" in t.call("list_jobs", {}) and "вода" in t.background_status()
    assert t.call("cancel_reminder", {"query": "вода"}).startswith("Скасувала")
    assert "Нагадувань і таймерів зараз немає" in t.background_status()
