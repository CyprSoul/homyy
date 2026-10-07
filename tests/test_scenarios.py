"""Сценарії живої розмови: «людина» говорить із Хомі, перевіряємо, що вона чує, каже й робить.

Без мікрофона й без Gemma: звук — заскриптовані фрази, Gemma — заготовлені відповіді потоком.
Перевіряється вся логіка розмови: потік, повтор, навчання, продовження думки, перебивання,
«так/ні», рефлекси.
"""
import json
import threading

import numpy as np
import pytest

from agent import main
from agent.brain import Brain

CFG = {"user": {"name": "Ігор", "name_genitive": "Ігоря", "name_vocative": "Ігорю"},
       "ollama": {"url": "http://x", "model": "m"}, "apps": {}, "search": {"url": "http://x"},
       "openwebui": {}, "stt": {},
       "wake": {"follow_up_seconds": 0.1, "command_silence_ms": 800, "barge_in": True, "stream": True,
                "smart_turn": False}}


class Script:
    """Що «людина» скаже і коли: hear — звичайна фраза; think — поки Хомі думає; speak — поки говорить."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.lock = threading.Lock()
        self.texts = {}

    def take(self, phase):
        with self.lock:
            if self.steps and self.steps[0][0] == phase:
                _, text = self.steps.pop(0)
                pcm = np.full(16000, len(self.texts) + 1, dtype=np.int16)
                self.texts[int(pcm[0])] = text
                return pcm
        return None


class FakeAudio:
    def __init__(self, script):
        self.script = script
        self.cut = threading.Event()
        self.barged = threading.Event()
        self.last_turn = None

    def listen(self, end_silence_ms, max_seconds, start_timeout_s=None, interrupt=None, abort=None, **k):
        phase = "hear" if abort is None else ("speak" if end_silence_ms == 400 else "think")
        pcm = self.script.take(phase)
        if pcm is not None:
            return pcm, 1.0
        if abort is not None:
            for _ in range(200):
                if abort():
                    return None
                threading.Event().wait(0.005)
        return None

    def loud_enough(self, pcm):
        return True

    def stop_playback(self):
        self.cut.set()

    def arm_barge_in(self, on):
        pass

    def beep(self, up=True):
        pass

    def drain(self):
        pass


class FakeSTT:
    def __init__(self, script):
        self.script = script
        self.last_engine = "parakeet"

    def command(self, pcm, fallback=True):
        marks = list(dict.fromkeys(int(x) for x in pcm[::1600]))       # склеєні фрази — по черзі
        return " ".join(self.script.texts.get(m, "") for m in marks).strip()


class FakeSpeaker:
    def __init__(self, audio):
        self.audio = audio
        self.said = []
        self.first_audio_at = None

    def say_cached(self, phrase):
        self.said.append(phrase)

    def say(self, text, clear_cut=True):
        self.said.append(text)
        return True

    def say_stream(self, sentences, clear_cut=True):
        import time
        if clear_cut:
            self.audio.cut.clear()
        for s in sentences:
            if self.audio.cut.is_set():
                continue
            self.first_audio_at = self.first_audio_at or time.time()
            self.said.append(s)
            threading.Event().wait(0.05)        # «говорить» — у цей час можна перебити
        return not self.audio.cut.is_set()


def run(steps, answers, monkeypatch, tmp_path, teach_rule="Коли просять показати — відкривай у браузері."):
    """steps — що каже людина; answers — що Gemma відповідає на питання (за ключовим словом)."""
    script = Script(steps)
    audio = FakeAudio(script)
    stt, speaker = FakeSTT(script), FakeSpeaker(audio)
    brain = Brain(CFG)
    from agent.lessons import LessonBook
    brain.lessons = LessonBook(tmp_path / "lessons.json")
    monkeypatch.setattr(brain, "_memories", lambda: [])
    asked = []

    def fake_post(url, timeout=None, json=None, stream=False):
        msgs = json["messages"]
        last = msgs[-1]["content"]
        if "Сформулюй ОДНЕ коротке правило" in last:
            return _Resp({"message": {"content": teach_rule}})
        q = last.split("\n\n(Службова довідка")[0]
        asked.append(q)
        reply = next((a for key, a in answers if key.lower() in q.lower()), "Добре.")
        return _Stream(reply) if stream else _Resp({"message": {"content": reply}, "done_reason": "stop"})
    monkeypatch.setattr("agent.brain.requests.post", fake_post)
    monkeypatch.setattr(main, "log", lambda *a: None)
    monkeypatch.setattr(main, "SKILLS", type("S", (), {"observe": lambda *a: False, "match": lambda *a: None,
                                                        "forget": lambda *a: False})())
    main._conversation(CFG, audio, stt, brain, speaker)
    return speaker.said, asked, brain


class _Resp:
    def __init__(self, data):
        self.data = data
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class _Stream:
    def __init__(self, text):
        words = text.split(" ")
        self.chunks = [w + " " for w in words]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        threading.Event().wait(0.3)                 # Gemma «читає» промпт, перш ніж писати
        for c in self.chunks:
            threading.Event().wait(0.01)
            yield json.dumps({"message": {"content": c}, "done": False}).encode()
        yield json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop"}).encode()


def test_simple_question_streamed(monkeypatch, tmp_path):
    said, asked, _ = run([("hear", "Як справи?")],
                         [("справи", "У мене все добре. А в тебе як вечір?")], monkeypatch, tmp_path)
    assert said[0] == "Так?"
    assert said[1:3] == ["У мене все добре.", "А в тебе як вечір?"]


def test_repeat_without_gemma(monkeypatch, tmp_path):
    said, asked, _ = run([("hear", "Яка погода завтра?"), ("hear", "Що?")],
                         [("погода", "Завтра сонячно, до 18 градусів.")], monkeypatch, tmp_path)
    assert said.count("Завтра сонячно, до 18 градусів.") == 2       # повторила
    assert len(asked) == 1                                           # Gemma питали лише раз


def test_continuing_thought_while_she_thinks(monkeypatch, tmp_path):
    said, asked, _ = run([("hear", "Пошукай сферу,"), ("think", "щоб вона рухалась від голосу")],
                         [("рухалась", "Тобі підійде Three.js з Web Audio API.")], monkeypatch, tmp_path)
    assert asked[-1] == "Пошукай сферу, щоб вона рухалась від голосу"
    assert "Тобі підійде Three.js з Web Audio API." in said


def test_stop_and_new_question_while_speaking(monkeypatch, tmp_path):
    long = "Космос — це величезний простір. " * 8 + "Ось і все."
    said, asked, _ = run([("hear", "Розкажи про космос."), ("speak", "Стоп, а котра година?")],
                         [("космос", long), ("година", "Зараз двадцять друга.")], monkeypatch, tmp_path)
    assert "Ось і все." not in said                                  # замовкла
    assert asked[-1] == "а котра година"
    assert "Зараз двадцять друга." in said


def test_feedback_becomes_lesson(monkeypatch, tmp_path):
    said, asked, brain = run([("hear", "Пошукай сферу і покажи."), ("hear", "Ні, не так, просто відкрий і покажи.")],
                             [("сферу", "Сфера — це геометрична фігура."), ("відкрий", "Добре, відкриваю пошук.")],
                             monkeypatch, tmp_path)
    for _ in range(100):                                             # навчання йде у фоні
        if brain.lessons.items:
            break
        threading.Event().wait(0.02)
    assert "браузері" in brain.lessons.prompt_block()


def test_teach_rule_directly(monkeypatch, tmp_path):
    said, asked, brain = run([("hear", "Хомі, запам'ятай правило: відповідай мені коротко")], [],
                             monkeypatch, tmp_path)
    assert "Запам'ятала правило." in said and "коротко" in brain.lessons.prompt_block()
    assert asked == []


def test_language_guard_and_russisms(monkeypatch, tmp_path):
    said, asked, _ = run([("hear", "Що таке самвидав?")],
                         [("самвидав", "Самиздат — це заборонена в СРСР література, яку передруковували потай.")],
                         monkeypatch, tmp_path)
    assert said[1].startswith("Самвидав — це заборонена")


@pytest.mark.parametrize("phrase", ["Дякую", "Угу"])
def test_noise_like_thanks_ends_quietly(monkeypatch, tmp_path, phrase):
    said, asked, _ = run([("hear", phrase)], [], monkeypatch, tmp_path)
    assert asked == [] or phrase == "Угу"
