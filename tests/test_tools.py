from agent.tools import Tools

CFG = {"apps": {"Steam": "steam://open/main"}, "search": {"url": "http://x"}, "openwebui": {}}


def test_schemas_valid():
    names = [s["function"]["name"] for s in Tools(CFG).schemas()]
    assert {"current_datetime", "date_difference", "web_search", "remember", "media",
            "open_app", "open_website", "mark_game", "look_at_screen"} <= set(names)


def test_unknown_and_safe_failures():
    t = Tools(CFG)
    assert "Невідомий" in t.call("rm_rf", {})
    assert "немає в списку" in t.call("open_app", {"name": "regedit"})
    assert "http" in t.call("open_website", {"url": "file:///C:/Windows"})
    assert "не підключена" in t.call("remember", {"fact": "x"})
    assert "6, \"days\": 17" in t.call("date_difference", {"from_date": "2026-03-18", "to_date": "2026-10-05"})


def test_example_config_parses():
    from agent.config import AGENT_DIR, load_config
    cfg = load_config(AGENT_DIR / "config.example.toml")
    assert cfg["apps"]["блокнот"] == "notepad.exe" and cfg["wake"]["min_seconds"] == 0.6


def test_obsidian_notes(tmp_path):
    (tmp_path / "Тренування.md").write_text("План: присідання 3x15, віджимання 3x10.", encoding="utf-8")
    t = Tools({**CFG, "obsidian": {"vault": str(tmp_path)}})
    assert "присідання" in t.call("notes_search", {"query": "тренування"})
    assert "Записала" in t.call("notes_add", {"text": "купити протеїн"})
    assert "купити протеїн" in (tmp_path / "Хомі.md").read_text(encoding="utf-8")
    assert "не підключені" in Tools(CFG).call("notes_search", {"query": "x"})


def test_search_on_site(monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert "rozetka" in Tools(CFG).call("search_on_site", {"site": "розетка", "query": "навушники"})
    assert opened == ["https://rozetka.com.ua/ua/search/?text=%D0%BD%D0%B0%D0%B2%D1%83%D1%88%D0%BD%D0%B8%D0%BA%D0%B8"]


def test_user_config_overrides_defaults(tmp_path):
    from agent.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('[wake]\nmin_seconds = 0.7\n[apps]\n"танки" = "wot.exe"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg["wake"]["min_seconds"] == 0.7 and cfg["wake"]["max_words"] == 3   # своє + стандартне
    assert cfg["apps"]["танки"] == "wot.exe" and "steam" in cfg["apps"]
    assert cfg["game"]["voice_wake"] is False and "obsidian" in cfg


def test_unconfigured_integrations_hidden():
    from agent.tools import Tools
    cfg = {"apps": {}, "search": {"url": "http://x"}, "openwebui": {}}
    names = {s["function"]["name"] for s in Tools(cfg).schemas()}
    assert "web_search" in names and not names & {"notes_search", "money_balance", "mail_unread"}
    cfg["monobank"] = {"token": "t"}
    assert "money_balance" in {s["function"]["name"] for s in Tools(cfg).schemas()}


def test_play_music(monkeypatch):
    from agent.tools import Tools
    t = Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert "вподобані" in t.call("play_music", {})
    assert opened[-1] == "https://music.youtube.com/watch?list=LM"
    monkeypatch.setattr(Tools, "_first_video", staticmethod(lambda q: "dQw4w9WgXcQ"))
    t.call("play_music", {"query": "Океан Ельзи"})
    assert opened[-1] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    monkeypatch.setattr(Tools, "_first_video", staticmethod(lambda q: None))
    assert "натиснути" in t.call("play_music", {"query": "щось"})
