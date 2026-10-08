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


class FakeVad:
    def is_speech(self, frame, rate):
        return any(frame[:4])


def _frames(a, pattern):
    """pattern: послідовність (мовлення?, кадрів по 30 мс)."""
    for speech, n in pattern:
        for _ in range(n):
            a.frames.put((b"\x10\x10" if speech else b"\x00\x00") * audio_mod.FRAME_SAMPLES)


def test_listen_waits_while_smart_turn_says_not_done(monkeypatch):
    monkeypatch.setattr(audio_mod.sd, "RawInputStream", FakeIn, raising=False)
    monkeypatch.setattr(audio_mod.sd, "OutputStream", FakeOut, raising=False)
    monkeypatch.setattr(audio_mod, "webrtcvad", type("V", (), {"Vad": lambda *a: FakeVad()}))
    a = audio_mod.Audio({})
    answers = iter([False, True])          # перша пауза — «ще думає», друга — «договорив»
    calls = []

    def turn(pcm):
        calls.append(len(pcm))
        return next(answers)
    # «Я хочу…» (1 с) · пауза 0.6 с · «…щоб ти нагадала» (1 с) · тиша
    _frames(a, [(True, 33), (False, 20), (True, 33), (False, 40)])
    pcm, speech_s = a.listen(end_silence_ms=300, max_seconds=30, turn=turn, max_silence_ms=2500)
    assert len(calls) == 2                               # не обірвала на першій паузі
    assert len(pcm) >= (33 + 20 + 33) * audio_mod.FRAME_SAMPLES


def test_long_story_is_not_cut_at_record_limit(monkeypatch):
    """Довга розповідь (довше за шматок запису) — Хомі слухає далі й склеює, а не відповідає посеред думки."""
    import numpy as np
    from agent import main
    chunks = [("limit", 30), ("limit", 30), ("turn", 5)]

    class A:
        last_turn = (0.9, 300)
        last_end = None

        def listen(self, **k):
            end, sec = chunks.pop(0)
            self.last_end = end
            return np.zeros(sec * 16000, dtype=np.int16), float(sec)
    monkeypatch.setitem(main.TURN, "model", type("M", (), {"probability": lambda self, pcm: 0.9})())
    monkeypatch.setattr(main.ui, "set_state", lambda *a: None)
    cfg = {"wake": {"turn_max_seconds": 30}}
    text, _, _ = main._hear_smart(cfg, A(), 8, None, lambda pcm: f"{len(pcm) // 16000} с")
    assert text == "65 с" and not chunks


def test_quiet_noise_is_not_recognized(monkeypatch):
    """Тихий шум, на який спрацював детектор мови, не йде в розпізнавач (там він стає «Так.»)."""
    import numpy as np
    from agent import main
    heard = []

    class A:
        last_turn, last_end = (0.98, 300), "turn"

        def listen(self, **k):
            return np.zeros(16000, dtype=np.int16), 0.5

        def loud_enough(self, pcm, factor=4.0):
            return False
    monkeypatch.setitem(main.TURN, "model", type("M", (), {"probability": lambda self, pcm: 0.9})())
    monkeypatch.setattr(main.ui, "set_state", lambda *a: None)
    text, _, _ = main._hear_smart({"wake": {}}, A(), 8, None, lambda pcm: heard.append(1) or "Так.")
    assert text == "" and not heard
