"""Розпізнавання мови: NVIDIA Canary / Parakeet (onnx-asr, процесор) або faster-whisper.

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

from .text import looks_ukrainian


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
        self.fallbacks = 0
        self.last_engine = ""
        self.threads = int(s.get("cpu_threads", 16))
        self.language = s.get("language", "uk")
        self.beam_size = int(s.get("beam_size", 1))

        print(f"Завантажую модель для «Хомі»: {s['wake_model']} (процесор)…")
        self.wake_model = WhisperModel(s["wake_model"], device="cpu", compute_type="int8", cpu_threads=self.threads)

        self.cpu_model = None
        self.gpu_model = None
        self.onnx = None                 # Parakeet / Canary (onnx-asr, процесор)
        self.onnx_opts: dict = {}
        self.backup = None               # запасний: Canary з примусовою українською
        self.backup_opts: dict = {}
        self.engine = s.get("engine", "whisper")
        if self.engine in ("canary", "parakeet"):
            self.onnx, self.onnx_opts = self._load_onnx(self.engine)
            other = "canary" if self.engine == "parakeet" else "parakeet"
            if self.onnx is None:                                  # не вийшло — пробуємо інший
                self.engine = other
                self.onnx, self.onnx_opts = self._load_onnx(other)
            elif self.engine == "parakeet" and s.get("fallback_engine", "canary") == "canary":
                # Parakeet сам вгадує мову й інколи пише російською — тоді перепитуємо Canary (≈0.2 с)
                threading.Thread(target=self._load_backup, daemon=True).start()
        if self.onnx is None:
            self.engine = "whisper"
            print(f"Завантажую модель для команд: {s['model']} (перший раз — кілька хвилин)…")
            if s.get("device", "auto") in ("auto", "cuda"):
                self.load_gpu()
            if self.gpu_model is None:
                self._ensure_cpu()
        elif s.get("whisper_fallback", False):
            threading.Thread(target=self._ensure_cpu, daemon=True).start()

    def _load_backup(self):
        model, opts = self._load_onnx("canary")
        self.backup_opts, self.backup = opts, model

    @property
    def parakeet(self):                  # сумісність: «чи працює швидке розпізнавання»
        return self.onnx

    _ONNX_MODELS = {"parakeet": "nemo-parakeet-tdt-0.6b-v3", "canary": "nemo-canary-1b-v2"}

    def _load_onnx(self, engine: str):
        """NVIDIA Canary / Parakeet на процесорі: не доповнюють фразу до 30 с, як Whisper, тому
        коротка команда розпізнається за десяті частки секунди й не займає відеокарту.
        Canary вміє примусово слухати українську (Parakeet вгадує мову сам і інколи помиляється)."""
        name = self._ONNX_MODELS[engine]
        try:
            import onnx_asr
            import onnxruntime as ort
            print(f"Завантажую {engine} для команд (перший раз ~0.7–1 ГБ)…")
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = int(self.cfg.get("onnx_threads", self.cfg.get("parakeet_threads", 8)))
            try:      # стиснена версія (int8) швидша; якщо її немає — повна
                model = onnx_asr.load_model(name, quantization="int8",
                                            providers=["CPUExecutionProvider"], sess_options=opts)
            except Exception:
                model = onnx_asr.load_model(name, providers=["CPUExecutionProvider"], sess_options=opts)
            opts_ = {"language": self.language} if engine == "canary" else {}
            model.recognize(np.zeros(16000, dtype=np.float32), sample_rate=16000, **opts_)  # прогрів
            print(f"Розпізнавання команд — {engine} на процесорі ⚡")
            return model, opts_
        except Exception as e:
            print(f"{engine} не завантажився ({str(e)[:160]}).")
            return None, {}

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
            if self.onnx is not None:
                wav = self._f32(pcm)
                text = str(self.onnx.recognize(wav, sample_rate=16000, **self.onnx_opts)).strip()
                self.last_engine = self.engine
                if looks_ukrainian(text):
                    return text
                if len(text.split()) <= 2 and not any("а" <= c <= "ї" for c in text.lower()):
                    return ""                # «Uh», «Hm» — шум, а не мова
                self.fallbacks += 1          # вийшло не українською — перепитуємо Canary, потім Whisper
                if self.backup is not None:
                    alt = str(self.backup.recognize(wav, sample_rate=16000, **self.backup_opts)).strip()
                    self.last_engine = f"{self.engine}→canary"
                    if looks_ukrainian(alt) or self.cpu_model is None:
                        return alt
                if self.cpu_model is None:
                    return text
            self.last_engine = "whisper"
            segs, _ = self.model.transcribe(self._f32(pcm), language=self.language, beam_size=self.beam_size,
                                            condition_on_previous_text=False, vad_filter=True)
            return " ".join(s.text for s in segs).strip()
