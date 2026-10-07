import sys
import types

import pytest

for _name in ("sounddevice", "webrtcvad"):          # звукових бібліотек на тестовій машині може не бути
    sys.modules.setdefault(_name, types.ModuleType(_name))


@pytest.fixture(autouse=True, scope="session")
def _quiet_log(tmp_path_factory):
    """Журнал тестів — у тимчасову папку, а не в agent/homyy.log (фонові потоки пишуть і після тесту)."""
    from agent import main
    main.LOG_FILE = tmp_path_factory.mktemp("log") / "homyy.log"
    main._HEADLESS = True
    yield
