"""Персональний детектор «Хооміі»: вчиться на записах голосу господаря.

Звук → мел-спектрограма → «відбиток» мовлення (готова нейромережа Google speech_embedding,
у форматі openWakeWord) → маленька логістична регресія, натренована саме на твоєму «Хооміі»
проти схожих слів («в домі», «вдома», «Хома») і звичайних звуків (Discord, гра, музика).
"""
import json
import urllib.request
from pathlib import Path

import numpy as np

AGENT_DIR = Path(__file__).resolve().parent
MODELS_DIR = AGENT_DIR / "models"
DATA_DIR = AGENT_DIR / "wake_data"
MODEL_FILE = AGENT_DIR / "wake_model.json"
FEATURE_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/{}.onnx"
RATE = 16000
CLIP_SECONDS = 1.6          # кожен фрагмент доводимо до однакової довжини


def _ensure_models():
    MODELS_DIR.mkdir(exist_ok=True)
    for name in ("melspectrogram", "embedding_model"):
        path = MODELS_DIR / f"{name}.onnx"
        if not path.exists():
            print(f"Завантажую {name}.onnx…")
            urllib.request.urlretrieve(FEATURE_URL.format(name), path)


class Features:
    def __init__(self):
        import onnxruntime as ort
        _ensure_models()
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        cpu = ["CPUExecutionProvider"]
        self.mel = ort.InferenceSession(str(MODELS_DIR / "melspectrogram.onnx"), opts, providers=cpu)
        self.emb = ort.InferenceSession(str(MODELS_DIR / "embedding_model.onnx"), opts, providers=cpu)

    @staticmethod
    def fit_length(pcm: np.ndarray, align: str = "center") -> np.ndarray:
        """Обрізає чи доповнює тишею до CLIP_SECONDS, тримаючи мовлення посередині
        (align="start" — бере початок: «Хомі» на початку довгої фрази «Хомі, яка погода?»)."""
        n = int(RATE * CLIP_SECONDS)
        pcm = pcm.astype(np.int16)
        if len(pcm) >= n:
            start = 0 if align == "start" else (len(pcm) - n) // 2
            return pcm[start:start + n]
        pad = n - len(pcm)
        return np.pad(pcm, (pad // 2, pad - pad // 2))

    def vector(self, pcm: np.ndarray, align: str = "center") -> np.ndarray:
        """Один вектор-«відбиток» фрагмента: середнє, максимум і розкид по кадрах."""
        x = self.fit_length(pcm, align).astype(np.float32)[None, :]
        spec = np.squeeze(self.mel.run(None, {"input": x})[0]) / 10 + 2          # (кадри, 32)
        windows = [spec[i:i + 76] for i in range(0, spec.shape[0] - 75, 8)]
        batch = np.array(windows, dtype=np.float32)[..., None]
        e = self.emb.run(None, {"input_1": batch})[0].reshape(len(windows), 96)
        return np.concatenate([e.mean(0), e.max(0), e.std(0)])


def augment(pcm: np.ndarray, rng: np.random.Generator, n: int) -> list[np.ndarray]:
    """Варіації запису: тихіше/гучніше, шум, зсув — щоб детектор не «завчив» один запис."""
    out = [pcm]
    x = pcm.astype(np.float32)
    for _ in range(n):
        y = x * 10 ** (rng.uniform(-8, 6) / 20)
        y = np.roll(y, int(rng.uniform(-0.15, 0.15) * RATE))
        y = y + rng.normal(0, rng.uniform(30, 400), len(y))
        out.append(np.clip(y, -32768, 32767).astype(np.int16))
    return out


def _train_lr(X: np.ndarray, y: np.ndarray, l2: float = 1.0, steps: int = 600) -> tuple[np.ndarray, float]:
    w, b = np.zeros(X.shape[1]), 0.0
    pos_w = (y == 0).sum() / max(1, (y == 1).sum())       # балансуємо класи
    sw = np.where(y == 1, pos_w, 1.0)
    for i in range(steps):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = (p - y) * sw
        lr = 0.5 / (1 + i / 200)
        w -= lr * (X.T @ g / len(y) + l2 * w / len(y))
        b -= lr * g.mean()
    return w, b


class WakeModel:
    def __init__(self, mean, std, w, b, threshold):
        self.mean, self.std, self.w, self.b, self.threshold = map(np.asarray, (mean, std, w, b, threshold))

    def score(self, vec: np.ndarray) -> float:
        z = (vec - self.mean) / self.std
        return float(1 / (1 + np.exp(-(z @ self.w + self.b))))

    @classmethod
    def train(cls, pos: list[np.ndarray], neg: list[np.ndarray], folds: int = 5, seed: int = 0):
        """pos/neg — уже пораховані вектори (з аугментацією). Поріг — за перехресною перевіркою."""
        X = np.array(pos + neg)
        y = np.array([1] * len(pos) + [0] * len(neg), dtype=float)
        mean, std = X.mean(0), X.std(0) + 1e-6
        Z = (X - mean) / std

        rng = np.random.default_rng(seed)
        fold = rng.integers(0, folds, len(y))
        cv = np.zeros(len(y))
        for k in range(folds):
            tr, te = fold != k, fold == k
            w, b = _train_lr(Z[tr], y[tr])
            cv[te] = 1 / (1 + np.exp(-(Z[te] @ w + b)))
        # поріг: вище за 98% «чужих» звуків, але так, щоб більшість твоїх «Хооміі» проходила
        neg_hi = np.quantile(cv[y == 0], 0.98)
        pos_lo = np.quantile(cv[y == 1], 0.15)
        threshold = float(np.clip(max(neg_hi + 0.05, (neg_hi + pos_lo) / 2), 0.5, 0.97))
        w, b = _train_lr(Z, y)
        stats = {"positives_ok": float((cv[y == 1] >= threshold).mean()),
                 "negatives_rejected": float((cv[y == 0] < threshold).mean()),
                 "threshold": threshold}
        return cls(mean, std, w, b, threshold), stats

    def save(self, path: Path = MODEL_FILE):
        path.write_text(json.dumps({k: np.asarray(getattr(self, k)).tolist()
                                    for k in ("mean", "std", "w", "b", "threshold")}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path = MODEL_FILE):
        if not path.exists():
            return None
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(d["mean"], d["std"], d["w"], d["b"], d["threshold"])
