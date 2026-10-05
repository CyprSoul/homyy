"""Розпізнавання мови через faster-whisper (на процесорі, відеокарта — для Gemma)."""
import numpy as np
from faster_whisper import WhisperModel


class STT:
    def __init__(self, cfg: dict):
        s = cfg["stt"]
        common = dict(device=s.get("device", "cpu"), compute_type=s.get("compute_type", "int8"),
                      cpu_threads=int(s.get("cpu_threads", 8)))
        self.language = s.get("language", "uk")
        self.beam_size = int(s.get("beam_size", 1))
        print(f"Завантажую модель для «Хомі»: {s['wake_model']}…")
        self.wake_model = WhisperModel(s["wake_model"], **common)
        print(f"Завантажую модель для команд: {s['model']} (перший раз — кілька хвилин)…")
        self.model = WhisperModel(s["model"], **common)

    @staticmethod
    def _f32(pcm: np.ndarray) -> np.ndarray:
        return pcm.astype(np.float32) / 32768.0

    def wake(self, pcm: np.ndarray) -> str:
        segs, _ = self.wake_model.transcribe(self._f32(pcm), language=self.language, beam_size=1,
                                             condition_on_previous_text=False,
                                             initial_prompt="Хоооумммііі. Хомі.")
        return " ".join(s.text for s in segs).strip()

    def command(self, pcm: np.ndarray) -> str:
        segs, _ = self.model.transcribe(self._f32(pcm), language=self.language, beam_size=self.beam_size,
                                        condition_on_previous_text=False, vad_filter=True)
        return " ".join(s.text for s in segs).strip()
