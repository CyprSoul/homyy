import sys
import types

import pytest

for _name in ("sounddevice", "webrtcvad"):          # звукових бібліотек на тестовій машині може не бути
    sys.modules.setdefault(_name, types.ModuleType(_name))


@pytest.fixture
def system_calls(monkeypatch):
    """Усі «системні» дії Хомі в тестах — лише в список, а не справді. Раніше
    test_confirmation_is_enforced_by_code ставив СПРАВЖНЄ вимкнення ПК через годину (shutdown /s /t 3600)
    і не скасовував його."""
    import ctypes
    import os

    from agent import pctools
    calls: list[list[str]] = []

    def fake_run(cmd, **kw):
        calls.append([str(c) for c in cmd])
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(pctools, "_run", fake_run)
    monkeypatch.setattr(os, "startfile", lambda *a, **k: calls.append(["startfile", *map(str, a)]), raising=False)
    if sys.platform == "win32":
        monkeypatch.setattr(ctypes.windll.user32, "LockWorkStation",
                            lambda: calls.append(["LockWorkStation"]), raising=False)
    return calls


@pytest.fixture(autouse=True)
def _isolated_pages_dir(monkeypatch, tmp_path):
    """Тести не створюють і не читають справжні сторінки в Документах."""
    from agent import builder
    monkeypatch.setattr(builder, "PAGES_DIR", tmp_path / "pages")


@pytest.fixture(autouse=True)
def _no_real_system_side_effects(system_calls):
    """Жоден тест не вимикає ПК, не присипляє, не блокує екран і не закриває програми по-справжньому."""
    yield


@pytest.fixture(autouse=True, scope="session")
def _quiet_log(tmp_path_factory):
    """Журнал тестів — у тимчасову папку, а не в agent/homyy.log (фонові потоки пишуть і після тесту)."""
    from agent import main
    main.LOG_FILE = tmp_path_factory.mktemp("log") / "homyy.log"
    main._HEADLESS = True
    yield
