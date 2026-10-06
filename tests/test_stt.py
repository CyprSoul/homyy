import sys
import types

import numpy as np

# faster-whisper не потрібен для цього тесту — підміняємо заглушкою, якщо його немає
if "faster_whisper" not in sys.modules:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        sys.modules["faster_whisper"] = types.SimpleNamespace(WhisperModel=object)

from agent import stt as stt_mod  # noqa: E402


class FakeParakeet:
    def __init__(self):
        self.calls = []

    def recognize(self, wav, sample_rate=16000):
        self.calls.append((wav.dtype, sample_rate))
        return " Привіт, Хомі. "


def test_command_uses_parakeet_when_loaded(monkeypatch):
    fake = FakeParakeet()
    monkeypatch.setattr(stt_mod, "WhisperModel", lambda *a, **k: object())
    monkeypatch.setattr(stt_mod.STT, "_load_parakeet", lambda self: fake)
    s = stt_mod.STT({"stt": {"engine": "parakeet", "wake_model": "small", "model": "large-v3-turbo"}})
    assert s.gpu_model is None and s.cpu_model is None          # Whisper для команд не вантажиться
    assert s.command(np.zeros(1600, dtype=np.int16)) == "Привіт, Хомі."
    assert fake.calls == [(np.float32, 16000)]
