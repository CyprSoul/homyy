import threading

import numpy as np

from agent import main


class FakeAudio:
    def __init__(self):
        self.cut = threading.Event()
        self.given = False

    def listen(self, *a, abort=None, **k):
        if not self.given:
            self.given = True
            return np.zeros(1600, dtype=np.int16), 1.0
        if abort is not None:
            abort()
        return None

    def stop_playback(self):
        self.cut.set()


class FakeSTT:
    def command(self, pcm):
        return "Стоп, стоп. А яка погода завтра?"


class FakeSpeaker:
    def __init__(self, audio):
        self.audio = audio

    def say(self, text):
        assert self.audio.cut.wait(3), "Хомі не замовкла"
        return False


def test_barge_in_returns_new_question(monkeypatch):
    monkeypatch.setattr(main, "log", lambda *a: None)
    audio = FakeAudio()
    cfg = {"wake": {"barge_in": True}}
    req = main.speak_listening(cfg, FakeSpeaker(audio), audio, FakeSTT(), "Сьогодні сонячно і тепло.")
    assert req == "а яка погода завтра"
