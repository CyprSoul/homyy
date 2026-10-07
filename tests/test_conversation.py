import sys
import threading
import types

import numpy as np

for _name in ("sounddevice", "webrtcvad"):          # звукових бібліотек на тестовій машині може не бути
    sys.modules.setdefault(_name, types.ModuleType(_name))

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
    def command(self, pcm, **kw):
        return "Стоп, стоп. А яка погода завтра?"


class FakeSpeaker:
    def __init__(self, audio):
        self.audio = audio

    def say(self, text, clear_cut=True):
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
    def command(self, pcm, **kw):
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


def test_double_talk_with_headphones_first_frame_is_you():
    from agent.audio import DoubleTalk
    dt = DoubleTalk(frames_needed=3)
    # у навушниках луни нема: мікрофон тихий, поки ти мовчиш…
    for _ in range(10):
        dt.update(0.012, 0.2, True)
    hits = [dt.update(0.2, 0.2, True) for _ in range(3)]       # …і ти заговорив
    assert hits[-1]


class TalkOverSTT:
    def command(self, pcm, **kw):
        return "Типу, я хочу зробити класну сферу, яка ворушиться"


def test_talking_over_continues_previous_request(monkeypatch):
    monkeypatch.setattr(main, "log", lambda *a: None)
    audio = FakeAudio()
    req = main.speak_listening({"wake": {}}, FakeSpeaker(audio), audio, TalkOverSTT(),
                               "Сфера — це геометрична фігура.", asked="Пошукай в інтернеті сферу.")
    assert req == "Пошукай в інтернеті сферу. Типу, я хочу зробити класну сферу, яка ворушиться"


class SlowBrain:
    def __init__(self):
        self.history = [{"role": "user", "content": "раніше"}]

    def ask(self, text, on_tool=None):
        import time as _t
        _t.sleep(0.3)
        self.history += [{"role": "user", "content": text}, {"role": "assistant", "content": "лекція"}]
        return "лекція"


class TalkingAudio:
    def __init__(self, talk):
        self.talk = talk

    def listen(self, *a, abort=None, **k):
        if self.talk:
            self.talk = False
            return np.zeros(1600, dtype=np.int16), 1.0
        while abort and not abort():
            pass
        return None


class MoreSTT:
    def command(self, pcm, **kw):
        return "щоб вона рухалась, коли хтось говорить"


def test_keeps_listening_while_thinking(monkeypatch):
    monkeypatch.setattr(main, "log", lambda *a: None)
    brain = SlowBrain()
    more, answer = main.ask_while_listening({"wake": {}}, TalkingAudio(True), MoreSTT(), brain,
                                            "Пошукай сферу,")
    assert more == "Пошукай сферу, щоб вона рухалась, коли хтось говорить" and answer is None
    assert brain.history == [{"role": "user", "content": "раніше"}]        # відповідь викинута
    more, answer = main.ask_while_listening({"wake": {}}, TalkingAudio(False), MoreSTT(), SlowBrain(), "Привіт")
    assert more is None and answer == "лекція"
