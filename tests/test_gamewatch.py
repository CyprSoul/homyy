from agent.gamewatch import DEFAULT_IGNORE, classify


def test_game_detection():
    games = {"cs2.exe"}
    assert classify("cs2.exe", False, games, DEFAULT_IGNORE)          # гра зі списку, навіть у вікні
    assert classify("Cyberpunk2077.exe", True, games, DEFAULT_IGNORE)  # будь-що на весь екран
    assert not classify("chrome.exe", True, games, DEFAULT_IGNORE)     # YouTube на весь екран — не гра
    assert not classify("notepad.exe", False, games, DEFAULT_IGNORE)


def test_remember_games(tmp_path, monkeypatch):
    from agent import gamewatch
    monkeypatch.setattr(gamewatch, "LEARNED_FILE", tmp_path / "games.json")
    assert gamewatch.remember("Dota2.exe", True)
    assert not gamewatch.remember("dota2.exe", True)          # уже знає
    assert gamewatch.load_learned()["games"] == {"dota2.exe"}
    assert gamewatch.remember("dota2.exe", False)             # передумали — тепер «не гра»
    data = gamewatch.load_learned()
    assert "dota2.exe" in data["ignore"] and "dota2.exe" not in data["games"]
