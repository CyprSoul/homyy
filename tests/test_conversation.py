import threading

import numpy as np

from agent import main


class FakeAudio:
    def __init__(self):
        self.cut = threading.Event()
        self.barged = threading.Event()
        self.given = False

    def arm_barge_in(self, on):
        pass

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


def test_double_talk_detector():
    from agent.audio import DoubleTalk
    dt = DoubleTalk(frames_needed=3)
    for _ in range(20):                       # луна з колонки: мікрофон ≈ 0.2 від того, що граємо
        assert not dt.update(0.02, 0.1, True)
    assert not dt.update(0.2, 0.1, True)      # ти заговорив: у 10 разів гучніше за луну
    assert not dt.update(0.2, 0.1, True)
    assert dt.update(0.2, 0.1, True)          # ~0.1 с поспіль — перебив
    dt.reset()
    assert not dt.update(0.5, 0.0, True)      # нічого не грає — не рахуємо


class SilentSTT:
    def command(self, pcm):
        return ""


class VoiceOverAudio(FakeAudio):
    def listen(self, *a, abort=None, **k):
        self.barged.set()                     # «заговорив поверх» — сигнал від DoubleTalk
        self.cut.set()
        return None


def test_talking_over_her_stops_and_listens(monkeypatch):
    monkeypatch.setattr(main, "log", lambda *a: None)
    audio = VoiceOverAudio()
    req = main.speak_listening({"wake": {}}, FakeSpeaker(audio), audio, SilentSTT(), "Довга відповідь.")
    assert req == ""
