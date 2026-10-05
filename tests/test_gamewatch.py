from agent.gamewatch import DEFAULT_IGNORE, classify


def test_game_detection():
    games = {"cs2.exe"}
    assert classify("cs2.exe", False, games, DEFAULT_IGNORE)          # гра зі списку, навіть у вікні
    assert classify("Cyberpunk2077.exe", True, games, DEFAULT_IGNORE)  # будь-що на весь екран
    assert not classify("chrome.exe", True, games, DEFAULT_IGNORE)     # YouTube на весь екран — не гра
    assert not classify("notepad.exe", False, games, DEFAULT_IGNORE)
