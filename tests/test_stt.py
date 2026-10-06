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


class FakeOnnx:
    def __init__(self, text):
        self.text, self.calls = text, []

    def recognize(self, wav, sample_rate=16000, **kw):
        self.calls.append((wav.dtype, sample_rate, kw))
        return self.text


class FakeWhisper:
    def transcribe(self, *a, **k):
        return [types.SimpleNamespace(text=" Привіт, як справи?")], None


CFG = {"stt": {"engine": "canary", "wake_model": "small", "model": "large-v3-turbo", "fallback_engine": "none"}}


def make(monkeypatch, text, engine="canary"):
    fake = FakeOnnx(text)

    def load(self, eng):
        return fake, ({"language": "uk"} if eng == "canary" else {})
    monkeypatch.setattr(stt_mod, "WhisperModel", lambda *a, **k: object())
    monkeypatch.setattr(stt_mod.STT, "_load_onnx", load)
    s = stt_mod.STT({"stt": dict(CFG["stt"], engine=engine)})
    return s, fake


def test_command_uses_canary_with_ukrainian(monkeypatch):
    s, fake = make(monkeypatch, " Привіт, Хомі. ")
    assert s.gpu_model is None and s.cpu_model is None          # Whisper для команд не вантажиться
    assert s.command(np.zeros(1600, dtype=np.int16)) == "Привіт, Хомі."
    assert fake.calls == [(np.float32, 16000, {"language": "uk"})]
    assert s.last_engine == "canary"


def test_wrong_language_goes_to_whisper(monkeypatch):
    s, _ = make(monkeypatch, "Ты тут, приведя кто расправы.", engine="parakeet")
    s.cpu_model = FakeWhisper()
    assert s.command(np.zeros(1600, dtype=np.int16)) == "Привіт, як справи?"
    assert s.fallbacks == 1 and s.last_engine == "whisper"


def test_parakeet_wrong_language_goes_to_canary(monkeypatch):
    s, _ = make(monkeypatch, "Ты тут, приведя кто расправы.", engine="parakeet")
    s.backup, s.backup_opts = FakeOnnx("Ти тут, привіт, як справи?"), {"language": "uk"}
    assert s.command(np.zeros(1600, dtype=np.int16)) == "Ти тут, привіт, як справи?"
    assert s.last_engine == "parakeet→canary"


def test_parakeet_short_latin_is_noise(monkeypatch):
    s, _ = make(monkeypatch, "Uh", engine="parakeet")
    s.backup = FakeOnnx("Дякую.")          # Canary на шумі вигадує «Дякую» — навіть не питаємо
    assert s.command(np.zeros(1600, dtype=np.int16)) == ""
