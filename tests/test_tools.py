from agent.tools import Tools

CFG = {"apps": {"Steam": "steam://open/main"}, "search": {"url": "http://x"}, "openwebui": {}}


def test_schemas_valid():
    names = [s["function"]["name"] for s in Tools(CFG).schemas()]
    assert {"current_datetime", "date_difference", "web_search", "remember", "media",
            "open_app", "open_website"} <= set(names)


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
    assert cfg["apps"]["блокнот"] == "notepad.exe" and cfg["wake"]["min_seconds"] == 1.0
