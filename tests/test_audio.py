import threading
import time

import sys
import types

import numpy as np

# На машині для тестів може не бути звукових бібліотек — підміняємо їх заглушками.
for name in ("sounddevice", "webrtcvad"):
    sys.modules.setdefault(name, types.ModuleType(name))

from agent import audio as audio_mod  # noqa: E402


class FakeIn:
    def __init__(self, **k): pass
    def start(self): pass


class FakeOut:
    latency = 0.0

    def __init__(self, callback, **k):
        self.cb = callback
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False


def test_play_goes_through_open_output_stream(monkeypatch):
    monkeypatch.setattr(audio_mod.sd, "RawInputStream", FakeIn, raising=False)
    monkeypatch.setattr(audio_mod.sd, "OutputStream", FakeOut, raising=False)
    monkeypatch.setattr(audio_mod, "webrtcvad", type("V", (), {"Vad": lambda *a: None}))
    a = audio_mod.Audio({})
    tone = (np.ones(2400) * 1000).astype(np.int16)        # 0.1 с при 24 кГц
    t = threading.Thread(target=a.play, args=(tone, 24000))
    t.start()
    got = []
    deadline = time.time() + 5
    while t.is_alive() and time.time() < deadline:
        buf = np.zeros((480, 1), dtype=np.float32)
        a.out_stream.cb(buf, 480)
        got.append(buf[:, 0].copy())
        time.sleep(0.001)
    t.join(1)
    out = np.concatenate(got)
    assert not t.is_alive()
    loud = np.flatnonzero(out > 0.01)
    # спершу тиша (щоб пристрій не з'їв початок), потім увесь тон: 0.1 с × 48 кГц
    assert loud[0] >= int(0.1 * audio_mod.OUT_RATE)
    assert abs(len(loud) - 4800) <= 2


def test_output_opens_only_for_speech(monkeypatch):
    monkeypatch.setattr(audio_mod.sd, "RawInputStream", FakeIn, raising=False)
    monkeypatch.setattr(audio_mod.sd, "OutputStream", FakeOut, raising=False)
    monkeypatch.setattr(audio_mod, "webrtcvad", type("V", (), {"Vad": lambda *a: None}))
    a = audio_mod.Audio({})
    assert not a.out_stream.active               # тиша — звук закритий, нічого не шипить
    a._ensure_output()
    assert a.out_stream.active


def test_loud_enough_ignores_quiet_noise(monkeypatch):
    monkeypatch.setattr(audio_mod.sd, "RawInputStream", FakeIn, raising=False)
    monkeypatch.setattr(audio_mod.sd, "OutputStream", FakeOut, raising=False)
    monkeypatch.setattr(audio_mod, "webrtcvad", type("V", (), {"Vad": lambda *a: None}))
    a = audio_mod.Audio({})
    a._levels.extend([0.004] * 300)                                   # тиха кімната
    rng = np.random.default_rng(0)
    quiet = (rng.normal(0, 0.006, 16000) * 32768).astype(np.int16)    # шум/луна
    voice = (rng.normal(0, 0.08, 16000) * 32768).astype(np.int16)     # голос біля мікрофона
    assert not a.loud_enough(quiet)
    assert a.loud_enough(voice)
