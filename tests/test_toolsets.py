from agent.tools import Tools
from agent.toolsets import CORE, select_tools

CFG = {"apps": {}, "search": {"url": "http://x"}, "openwebui": {}, "kiwix": {"url": "http://k"}}


def names(text, recent=""):
    return {s["function"]["name"] for s in select_tools(Tools(CFG).schemas(), text, recent)}


def test_core_is_always_there_and_set_is_smaller():
    all_names = {s["function"]["name"] for s in Tools(CFG).schemas()}
    chat = names("Розкажи про космос")
    assert CORE & all_names <= chat and len(chat) < len(all_names) // 2


def test_groups_follow_the_words():
    assert {"open_app", "close_app"} <= names("Запусти дискорд")
    assert {"media", "play_music"} <= names("Постав якусь пісню")
    assert {"make_page", "open_page"} <= names("Відкрий сторінку трекера")
    assert {"look_at_screen", "click_on_screen"} <= names("Подивись, що в мене на екрані")
    assert "shutdown_timer" in names("Вимкни комп'ютер через годину")
    assert "cancel_reminder" in names("Скасуй нагадування про воду")
    assert "forget_fact" in names("Забудь, що я люблю каву")


def test_follow_up_sees_tools_of_previous_turn():
    # «так» після «Закрити Discord?» — без попередньої репліки close_app зник би
    assert "close_app" not in names("Так, можна")
    assert "close_app" in names("Так, можна", "Хомі, закрий дискорд. Закрити Discord? Незбережене може пропасти.")


def test_unknown_mcp_tools_are_kept():
    extra = [{"type": "function", "function": {"name": "demo__add", "description": "", "parameters": {}}}]
    assert "demo__add" in {s["function"]["name"] for s in select_tools(Tools(CFG).schemas() + extra, "привіт")}


def test_off_by_default_and_on_by_config():
    assert len(Tools(CFG).schemas_for("Розкажи про космос")) == len(Tools(CFG).schemas())
    on = Tools({**CFG, "ollama": {"tool_select": True}})
    assert len(on.schemas_for("Розкажи про космос")) < len(on.schemas())
