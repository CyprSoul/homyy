"""Розпізнавання мови: faster-whisper або NVIDIA Parakeet (onnx-asr, процесор).

Команди — на відеокарті, якщо вийде (≈0.3 с замість ≈3 с на процесорі), інакше на процесорі.
Маленька модель для «Хомі» завжди на процесорі: їй вистачає, а відеопам'ять — для Gemma.
"""
import gc
import importlib.util
import os
import sys
import threading

import numpy as np
from faster_whisper import WhisperModel


def _enable_cuda_dlls():
    """На Windows бібліотеки CUDA з pip-пакетів nvidia-* треба явно показати системі."""
    if sys.platform != "win32":
        return
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime"):
        try:
            spec = importlib.util.find_spec(pkg)
        except ModuleNotFoundError:
            continue
        for loc in (spec.submodule_search_locations or []) if spec else []:
            dll_dir = os.path.join(loc, "bin")
            if os.path.isdir(dll_dir):
                os.add_dll_directory(dll_dir)
                os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


class STT:
    def __init__(self, cfg: dict):
        s = self.cfg = cfg["stt"]
        self.lock = threading.Lock()
        self.threads = int(s.get("cpu_threads", 16))
        self.language = s.get("language", "uk")
        self.beam_size = int(s.get("beam_size", 1))

        print(f"Завантажую модель для «Хомі»: {s['wake_model']} (процесор)…")
        self.wake_model = WhisperModel(s["wake_model"], device="cpu", compute_type="int8", cpu_threads=self.threads)

        self.cpu_model = None
        self.gpu_model = None
        self.parakeet = None
        if s.get("engine", "whisper") == "parakeet":
            self.parakeet = self._load_parakeet()
        if self.parakeet is None:
            print(f"Завантажую модель для команд: {s['model']} (перший раз — кілька хвилин)…")
            if s.get("device", "auto") in ("auto", "cuda"):
                self.load_gpu()
            if self.gpu_model is None:
                self._ensure_cpu()

    def _load_parakeet(self):
        """NVIDIA Parakeet v3 на процесорі: не доповнює фразу до 30 с, як Whisper, тому
        коротка команда розпізнається за десяті частки секунди й не займає відеокарту."""
        try:
            import onnx_asr
            import onnxruntime as ort
            print("Завантажую Parakeet для команд (перший раз ~700 МБ)…")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = int(self.cfg.get("parakeet_threads", 8))
            try:      # стиснена версія (int8) швидша; якщо її немає — повна
                model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8",
                                            providers=["CPUExecutionProvider"], sess_options=opts)
            except Exception:
                model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3",
                                            providers=["CPUExecutionProvider"], sess_options=opts)
            model.recognize(np.zeros(16000, dtype=np.float32), sample_rate=16000)   # прогрів
            print("Розпізнавання команд — Parakeet на процесорі ⚡")
            return model
        except Exception as e:
            print(f"Parakeet не завантажився ({str(e)[:160]}), беру Whisper.")
            return None

    def _ensure_cpu(self):
        if self.cpu_model is None:
            self.cpu_model = WhisperModel(self.cfg["model"], device="cpu",
                                          compute_type=self.cfg.get("compute_type", "int8"), cpu_threads=self.threads)

    def load_gpu(self) -> bool:
        try:
            _enable_cuda_dlls()
            model = WhisperModel(self.cfg["model"], device="cuda",
                                 compute_type=self.cfg.get("gpu_compute_type", "int8_float16"))
            list(model.transcribe(np.zeros(16000, dtype=np.float32), language=self.language)[0])  # пробний запуск
            self.gpu_model = model
            print("Розпізнавання команд — на відеокарті ⚡")
            return True
        except Exception as e:
            print(f"Відеокарта для розпізнавання не вийшла ({str(e)[:120]}), працюю на процесорі.")
            return False

    def release_gpu(self):
        """Ігровий режим: звільнити відеокарту, команди розпізнавати процесором."""
        if self.gpu_model is not None:
            self._ensure_cpu()
            self.gpu_model = None
            gc.collect()

    @property
    def model(self):
        return self.gpu_model or self.cpu_model

    @staticmethod
    def _f32(pcm: np.ndarray) -> np.ndarray:
        return pcm.astype(np.float32) / 32768.0

    def wake(self, pcm: np.ndarray) -> str:
        segs, _ = self.wake_model.transcribe(self._f32(pcm), language=self.language, beam_size=1,
                                             condition_on_previous_text=False,
                                             initial_prompt="Хоооумммііі. Хомі.")
        return " ".join(s.text for s in segs).strip()

    def command(self, pcm: np.ndarray) -> str:
        with self.lock:                  # голос із мікрофона й голосові з Telegram — по черзі
            if self.parakeet is not None:
                return str(self.parakeet.recognize(self._f32(pcm), sample_rate=16000)).strip()
            segs, _ = self.model.transcribe(self._f32(pcm), language=self.language, beam_size=self.beam_size,
                                            condition_on_previous_text=False, vad_filter=True)
            return " ".join(s.text for s in segs).strip()
