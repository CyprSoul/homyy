"""Чи договорила людина — за інтонацією й ритмом голосу, а не лише за тишею.

Модель Smart Turn v3.2 (Pipecat / Daily, BSD-2, підтримує українську): останні ≤8 с звуку →
ймовірність «фраза завершена». Так Хомі не перебиває, коли ти задумався посеред думки,
і не чекає зайвого, коли ти справді договорив. ~10–20 мс на процесорі.
"""
from pathlib import Path

import numpy as np

from .whisper_features import compute_whisper_log_mel_features

MODEL = Path(__file__).resolve().parent / "smart-turn-v3.2-cpu.onnx"
RATE = 16000


class SmartTurn:
    def __init__(self, threads: int = 1):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(MODEL), sess_options=so, providers=["CPUExecutionProvider"])

    def probability(self, pcm: np.ndarray) -> float:
        """pcm — int16 або float32, 16 кГц. Повертає ймовірність, що людина договорила (0..1)."""
        x = pcm.astype(np.float32)
        if pcm.dtype == np.int16:
            x /= 32768.0
        n = 8 * RATE
        x = x[-n:] if len(x) > n else np.pad(x, (n - len(x), 0))
        feats = compute_whisper_log_mel_features(x, do_normalize=True)[None, ...]
        return float(self.session.run(None, {"input_features": feats})[0][0].item())
