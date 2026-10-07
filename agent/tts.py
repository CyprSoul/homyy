"""Голос Хомі: основний (локальний український StyleTTS2) і запасний (Поліна через openai-edge-tts).

Якщо основний голос недоступний (контейнер не запущений), Хомі говорить запасним — не мовчить.
"""
import time
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
        # Один синтез за раз: так перше речення готується першим і найшвидше (паралельні запити
        # ділили процесор сервера голосу, і перше речення чекало 4–5 с), а наступне готується,
        # поки звучить попереднє.
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.cache: dict[str, np.ndarray] = {}
        self.first_audio_at = None

    def say_cached(self, phrase: str):
        """Коротка фраза («Так?»), синтезована один раз — звучить миттєво."""
        if phrase not in self.cache:
            self.cache[phrase] = self._synth(phrase)
        self.audio.play(self.cache[phrase], RATE)
        self.audio.drain()

    def warm(self, phrases: list[str]):
        """Синтезує короткі фрази у фоні, щоб перше «Так?» не чекало на сервер голосу."""
        def work():
            for p in phrases:
                try:
                    self.cache.setdefault(p, self._synth(p))
                except Exception:
                    pass
        self.pool.submit(work)

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

    def say_stream(self, sentences, clear_cut: bool = True) -> bool:
        """Говорить речення, щойно вони з'являються (Gemma ще дописує решту). False — якщо перебили."""
        import queue
        import threading
        cut = getattr(self.audio, "cut", None)
        if cut is not None and clear_cut:
            cut.clear()
        futs: "queue.Queue" = queue.Queue()

        def produce():
            try:
                for piece in sentences:
                    for s in split_sentences(clean_for_speech(piece)):
                        futs.put(self.pool.submit(self._synth, s))
            finally:
                futs.put(None)
        threading.Thread(target=produce, daemon=True).start()
        first = True
        while True:
            f = futs.get()
            if f is None:
                break
            if cut is not None and cut.is_set():
                f.cancel()
                continue                        # дочитуємо чергу, нічого не граючи
            samples = f.result()
            if first:
                self.first_audio_at = time.time()
                first = False
            self.audio.play(samples, RATE)
        if cut is not None and cut.is_set():
            return False
        self.audio.drain()
        return True

    def say(self, text: str, clear_cut: bool = True) -> bool:
        """Говорить по реченню. False — якщо перебили («стоп»)."""
        sentences = split_sentences(clean_for_speech(text))
        cut = getattr(self.audio, "cut", None)
        if cut is not None and clear_cut:
            cut.clear()
        futures = [self.pool.submit(self._synth, s) for s in sentences]
        for i, f in enumerate(futures):
            if cut is not None and cut.is_set():
                for rest in futures[i:]:
                    rest.cancel()
                return False
            samples = f.result()
            if i == 0:
                self.first_audio_at = time.time()      # для журналу: коли Хомі реально заговорила
            self.audio.play(samples, RATE)
        if cut is not None and cut.is_set():
            return False
        self.audio.drain()
        return True
