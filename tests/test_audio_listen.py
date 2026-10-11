import queue

import numpy as np

from agent.audio import FRAME_SAMPLES, Audio


class FakeVad:
    """VAD бачить мовлення лише в кадрах із позначкою 2 (м'який початок слова — позначка 1 — він пропускає)."""

    def is_speech(self, frame, rate):
        return np.frombuffer(frame, dtype=np.int16)[0] == 2


def frames(marker: int, n: int):
    return [np.full(FRAME_SAMPLES, marker, dtype=np.int16).tobytes() for _ in range(n)]


def make_audio():
    a = Audio.__new__(Audio)               # без мікрофона: лише логіка listen()
    a.vad = FakeVad()
    a.frames = queue.Queue()
    for f in frames(0, 20) + frames(1, 12) + frames(2, 10) + frames(0, 60):
        a.frames.put(f)
    return a


def onset_frames_in(pcm: np.ndarray) -> int:
    marks = pcm.reshape(-1, FRAME_SAMPLES)[:, 0]
    return int((marks == 1).sum())


def test_default_pre_roll_loses_soft_word_onset():
    pcm, _ = make_audio().listen(end_silence_ms=300, max_seconds=10)
    assert onset_frames_in(pcm) < 12                 # частина «м'якого» початку слова втрачена (300 мс буфера)


def test_longer_pre_roll_keeps_the_whole_word_onset():
    pcm, _ = make_audio().listen(end_silence_ms=300, max_seconds=10, pre_roll_ms=600)
    assert onset_frames_in(pcm) == 12                # весь початок слова на місці
