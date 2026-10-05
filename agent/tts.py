"""Голос Хомі: основний (локальний український StyleTTS2) і запасний (Поліна через openai-edge-tts).

Якщо основний голос недоступний (контейнер не запущений), Хомі говорить запасним — не мовчить.
"""
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

    @staticmethod
    def _request(v: dict, sentence: str) -> bytes:
        r = requests.post(v["url"], timeout=60,
                          headers={"Authorization": f"Bearer {v.get('api_key', '')}"},
                          json={"model": v.get("model", "tts-1"), "input": sentence, "voice": v["voice"],
                                "speed": float(v.get("speed", 1.0)), "response_format": "mp3"})
        r.raise_for_status()
        return r.content

    def _synth(self, sentence: str) -> np.ndarray:
        try:
            data = self._request(self.cfg, sentence)
        except requests.RequestException:
            fallback = self.cfg.get("fallback")
            if not fallback:
                raise
            data = self._request(fallback, sentence)
        decoded = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16,
                                   nchannels=1, sample_rate=RATE)
        return np.frombuffer(decoded.samples, dtype=np.int16)

    def say(self, text: str):
        sentences = split_sentences(clean_for_speech(text))
        # Усі речення синтезуються паралельно, а грають по черзі — перше звучить майже одразу.
        futures = [self.pool.submit(self._synth, s) for s in sentences]
        for f in futures:
            self.audio.play(f.result(), RATE)
        self.audio.drain()
