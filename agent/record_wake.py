"""Запис зразків і навчання персонального детектора «Хооміі».

Запуск:  .venv\\Scripts\\python -m agent.record_wake          — записати й навчити
         .venv\\Scripts\\python -m agent.record_wake --train  — лише перенавчити на вже записаному
Записи лишаються на ПК у agent\\wake_data. Повторний запуск ДОДАЄ нові записи до старих.
"""
import sys
import time
import wave

import numpy as np

from .wakeword import DATA_DIR, RATE, Features, WakeModel, augment

POSITIVES = 30
TRAPS = ["в домі", "вдома", "Хома", "хочу", "хто ми", "по домі", "у домі", "хом'як", "хоч би",
         "Хоми", "Томі", "комін", "хвилину", "хо-хо", "окей", "привіт"]
FREE_SECONDS = 90


def save(pcm: np.ndarray, kind: str):
    folder = DATA_DIR / kind
    folder.mkdir(parents=True, exist_ok=True)
    with wave.open(str(folder / f"{int(time.time() * 1000)}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.astype(np.int16).tobytes())


def load(kind: str) -> list[np.ndarray]:
    out = []
    for f in sorted((DATA_DIR / kind).glob("*.wav")):
        with wave.open(str(f), "rb") as w:
            out.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16))
    return out


def record(audio, prompt: str, kind: str, timeout: float = 8.0) -> bool:
    print(prompt, flush=True)
    audio.drain()
    audio.beep(up=True)
    seg = audio.listen(end_silence_ms=400, max_seconds=3, start_timeout_s=timeout)
    if seg is None:
        print("   …нічого не почула, спробуємо ще раз")
        return False
    save(seg[0], kind)
    print(f"   ✓ записала ({seg[1]:.1f} с)")
    return True


def collect(cfg):
    from .audio import Audio
    audio = Audio(cfg)
    print("\n=== 1/3. Твоє «Хооміі» ===")
    print("Кажи так, як кликатимеш Хомі в житті: звичайним голосом, трохи протяжно.")
    print("Можна по-різному: тихіше, гучніше, ближче й далі від мікрофона.\n")
    n = 0
    while n < POSITIVES:
        n += record(audio, f"[{n + 1}/{POSITIVES}] Скажи «Хооміі»", "positive")

    print("\n=== 2/3. Слова-пастки (схожі, але НЕ виклик) ===")
    for i, phrase in enumerate(TRAPS, 1):
        while not record(audio, f"[{i}/{len(TRAPS)}] Скажи: «{phrase}»", "negative"):
            pass

    print(f"\n=== 3/3. Звичайні звуки ({FREE_SECONDS} с) ===")
    print("Говори що завгодно (але НЕ «Хомі»), увімкни Discord, гру чи музику — усе, що буває поруч.")
    input("Натисни Enter, щоб почати… ")
    audio.drain()
    end, got = time.time() + FREE_SECONDS, 0
    while time.time() < end:
        seg = audio.listen(end_silence_ms=400, max_seconds=3, start_timeout_s=max(0.5, end - time.time()))
        if seg is not None:
            save(seg[0], "negative")
            got += 1
            print(f"   записано фрагментів: {got}", end="\r", flush=True)
    print(f"\n   ✓ {got} фрагментів")


def train():
    pos_raw, neg_raw = load("positive"), load("negative")
    if len(pos_raw) < 10 or len(neg_raw) < 10:
        print("Замало записів: треба хоча б 10 «Хооміі» і 10 інших звуків.")
        return
    print(f"\nНавчаюсь: {len(pos_raw)} «Хооміі», {len(neg_raw)} інших звуків…")
    f, rng = Features(), np.random.default_rng(0)
    pos = [f.vector(a) for p in pos_raw for a in augment(p, rng, 5)]
    neg = [f.vector(a) for p in neg_raw for a in augment(p, rng, 2)]
    model, stats = WakeModel.train(pos, neg)
    model.save()
    print(f"Готово! Поріг {stats['threshold']:.2f}. На перевірці: впізнаю твоє «Хооміі» в "
          f"{stats['positives_ok']:.0%} випадків, відкидаю чужі звуки в {stats['negatives_rejected']:.0%}.")
    if stats["positives_ok"] < 0.8:
        print("Порада: запиши ще 20–30 «Хооміі» (запусти програму ще раз) — стане точніше.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--train" not in sys.argv:
        from .config import load_config
        collect(load_config())
    train()
    print("\nПерезапусти Хомі, щоб вона почала користуватися детектором.")


if __name__ == "__main__":
    main()
