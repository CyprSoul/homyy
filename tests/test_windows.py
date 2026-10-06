from agent.windows import find_window

WINDOWS = [(1, "Windows PowerShell", "WindowsTerminal.exe"), (2, "#general | Discord", "Discord.exe"),
           (3, "YouTube Music - Google Chrome", "chrome.exe"), (4, "Steam", "steam.exe")]


def test_find_window_by_spoken_name():
    assert find_window("термінал", WINDOWS)[0] == 1
    assert find_window("дискорд", WINDOWS)[0] == 2
    assert find_window("музику", WINDOWS)[0] == 3
    assert find_window("стім", WINDOWS)[0] == 4
    assert find_window("фотошоп", WINDOWS) is None
