from agent.router import route


def test_forget_fact_is_a_quick_command():
    r = route("Забудь, що я люблю каву.")
    assert r.kind == "tool" and r.tool == "forget_fact" and r.args == {"query": "я люблю каву"}
    assert route("Хомі, забудь про каву").args == {"query": "каву"}
    assert route("Забудь, як відкривати стім").kind == "forget_skill"        # навички — окремо


def test_shutdown_is_a_quick_command_with_code_confirmation(system_calls):
    from agent.brain import Brain
    b = Brain({"user": {"name": "Ігор"}, "ollama": {"url": "http://x", "model": "m"}, "apps": {},
               "search": {"url": "http://x"}, "openwebui": {}})
    r = route("Закрий всі програми і виключи комп'ютер.")
    assert (r.tool, r.args) == ("shutdown_timer", {"minutes": 0})
    b.tools.last_user_text = "Закрий всі програми і виключи комп'ютер."
    assert b.direct("Закрий всі програми і виключи комп'ютер.", r.tool, r.args) == "Точно вимкнути комп'ютер зараз?"
    assert not system_calls                                     # без «так» нічого не запущено
    confirm = route("Так, вимикай.", b.tools.awaiting)
    b.tools.last_user_text = "Так, вимикай."
    assert b.direct("Так, вимикай.", confirm.tool, confirm.args).startswith("Готово: комп'ютер вимкнеться зараз")
    assert system_calls == [["shutdown", "/s", "/t", "0"]]


def test_route_order_media_before_brain():
    assert route("Хоми, постав на паузу.").tool == "media"
    assert route("зніме з паузи").args["action"] == "play"
    assert route("Розкажи про космос.") is None


def test_forget_fact_matches_by_keywords(monkeypatch):
    from agent import tools as tools_mod
    deleted = []
    memories = [{"id": "1", "content": "Ігор про себе: «Я не люблю каву.»"},
                {"id": "2", "content": "Ігор про себе: «Мого сина звати Андрій.»"}]

    class R:
        def __init__(self, data=None):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    monkeypatch.setattr(tools_mod.requests, "get", lambda *a, **k: R(memories))
    monkeypatch.setattr(tools_mod.requests, "delete", lambda url, **k: deleted.append(url) or R())
    t = tools_mod.Tools({"apps": {}, "openwebui": {"url": "http://x", "api_key": "k"}})
    assert t.call("forget_fact", {"query": "я люблю каву"}).startswith("Забула: Ігор про себе: «Я не люблю каву.»")
    assert deleted == ["http://x/api/v1/memories/1"]
    assert "нічого" in t.call("forget_fact", {"query": "футбол"})
