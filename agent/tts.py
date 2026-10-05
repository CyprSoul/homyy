"""Голос Поліни через контейнер openai-edge-tts."""
from concurrent.futures import ThreadPoolExecutor

import miniaudio
import numpy as np
import requests

from .text import clean_for_speech, split_sentences

RATE = 24000


class Speaker:
    def __init__(self, cfg: dict, audio):
        self.cfg = cfg["tts"]
        self.audio = audio
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.cache: dict[str, np.ndarray] = {}

    def say_cached(self, phrase: str):
        """Коротка фраза («Так?»), синтезована один раз — звучить миттєво."""
        if phrase not in self.cache:
            self.cache[phrase] = self._synth(phrase)
        self.audio.play(self.cache[phrase], RATE)
        self.audio.drain()

    def _synth(self, sentence: str) -> np.ndarray:
        r = requests.post(self.cfg["url"], timeout=30,
                          headers={"Authorization": f"Bearer {self.cfg.get('api_key', '')}"},
                          json={"model": self.cfg.get("model", "tts-1"), "input": sentence, "voice": self.cfg["voice"],
                                "speed": float(self.cfg.get("speed", 1.0)), "response_format": "mp3"})
        r.raise_for_status()
        decoded = miniaudio.decode(r.content, output_format=miniaudio.SampleFormat.SIGNED16,
                                   nchannels=1, sample_rate=RATE)
        return np.frombuffer(decoded.samples, dtype=np.int16)

    def say(self, text: str):
        sentences = split_sentences(clean_for_speech(text))
        # Усі речення синтезуються паралельно, а грають по черзі — перше звучить майже одразу.
        futures = [self.pool.submit(self._synth, s) for s in sentences]
        for f in futures:
            self.audio.play(f.result(), RATE)
        self.audio.drain()
