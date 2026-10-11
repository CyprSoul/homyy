"""Розпізнавачі на ТВОЄМУ голосі — з точністю в цифрах (WER, відсоток помилок у словах).

Ти читаєш 30 готових фраз, тож правильний текст відомий. Записи лишаються в agent\\stt_test\\, тому
нових кандидатів можна перевіряти без повторного читання.

Запис (Хомі має бути вимкнена; можна перервати Ctrl+C і продовжити пізніше):
    .venv\\Scripts\\python -m agent.stt_bench --record
Оцінка (Parakeet, Canary, Whisper і «як зараз у Хомі» — Parakeet, а не українською → Canary):
    .venv\\Scripts\\python -m agent.stt_bench
    .venv\\Scripts\\python -m agent.stt_bench --engines parakeet,canary     (лише вказані)
Результат ще й у agent\\stt_bench.txt.
"""
import re
import sys
import time
import wave

import numpy as np

from .config import AGENT_DIR, load_config

DIR = AGENT_DIR / "stt_test"
OUT = AGENT_DIR / "stt_bench.txt"
MIN_SPEECH = 0.5

PHRASES = [
    "Постав музику на паузу.",
    "Зроби гучність тихіше.",
    "Відкрий Діскорд.",
    "Який зараз час?",
    "Яка завтра погода в Києві?",
    "Нагадай мені через десять хвилин випити воду.",
    "Запам'ятай, що я люблю каву без цукру.",
    "Згорни це вікно.",
    "Відкрий папку з іграми на робочому столі.",
    "Знайди в інтернеті, як працює двигун внутрішнього згоряння.",
    "Хомі, а ти можеш мені допомогти з тренуванням?",
    "Я хочу, щоб ти зробила сторінку для запису тренувань.",
    "Розкажи, будь ласка, коротко, що таке самвидав.",
    "Що ти думаєш про те, щоб почати бігати вранці?",
    "Ні, не так, я мав на увазі зовсім інше.",
    "Дякую, це було дуже корисно, ти молодець.",
    "Вимкни комп'ютер через пів години.",
    "Покажи, що зараз відбувається на екрані.",
    "Натисни на кнопку «Продовжити».",
    "Увімкни щось спокійне, щоб я міг зосередитись.",
    "Запусти Стім і відкрий мою бібліотеку ігор.",
    "Відкрий Ютуб і знайди відео про сучасну архітектуру.",
    "Відкрий Телеграм і прочитай останнє повідомлення.",
    "Слухай, я тут подумав, що нам треба переробити розпізнавання мови, бо воно часто помиляється.",
    "Мені потрібен план тренувань на тиждень: три дні силових і два дні кардіо.",
    "Скільки коштуватимуть два квитки на поїзд до Львова?",
    "Зачекай, не відкривай, я передумав.",
    "Поясни, чому небо блакитне, але так, щоб я зрозумів з першого разу.",
    "Що ми з тобою обговорювали вчора ввечері?",
    "Добраніч, Хомі, побачимось завтра.",
]

# назви, які розпізнавач може написати латиницею, — зараховуємо як правильні
BRANDS = {"discord": "діскорд", "steam": "стім", "youtube": "ютуб", "telegram": "телеграм"}
RUSSIAN_LETTERS = set("ыэъё")


def normalize(text: str) -> list[str]:
    t = text.lower().replace("’", "'").replace("ʼ", "'")
    t = re.sub(r"[^\w\s']", " ", t)
    return [BRANDS.get(w, w) for w in t.split()]


def word_errors(ref: str, hyp: str) -> int:
    """Відстань Левенштейна між словами: підміни + пропуски + зайві слова."""
    r, h = normalize(ref), normalize(hyp)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1]


def save_wav(path, pcm: np.ndarray):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm.astype(np.int16).tobytes())


def load_wav(path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def record(cfg):
    from .audio import Audio
    audio = Audio(cfg)
    DIR.mkdir(exist_ok=True)
    todo = [i for i in range(len(PHRASES)) if not (DIR / f"{i + 1:02d}.wav").exists()]
    print(f"\nЧитай фрази так, як говориш із Хомі в житті. Лишилось {len(todo)} з {len(PHRASES)}.")
    print("Після сигналу читай фразу цілком, потім помовч. Не вийшло — просто скажи ще раз.\n", flush=True)
    for i in todo:
        while True:
            print(f"[{i + 1}/{len(PHRASES)}] «{PHRASES[i]}»", flush=True)
            audio.drain()
            audio.beep(up=True)
            seg = audio.listen(end_silence_ms=1200, max_seconds=15, start_timeout_s=12)
            if seg is None:
                print("   …нічого не почула, ще раз")
            elif seg[1] < MIN_SPEECH:
                print(f"   ✗ надто коротко ({seg[1]:.1f} с мовлення) — ще раз")
            else:
                save_wav(DIR / f"{i + 1:02d}.wav", seg[0])
                print(f"   ✓ записала ({len(seg[0]) / 16000:.1f} с)")
                break
    print("\nГотово. Тепер оцінка:  .venv\\Scripts\\python -m agent.stt_bench")


def load_engine(cfg, name):
    from .stt import STT
    c = {**cfg, "stt": {**cfg["stt"], "engine": name, "whisper_fallback": False,
                        "fallback_engine": "none", "device": "cpu"}}
    try:
        stt = STT(c)
    except Exception as e:
        print(f"{name}: не завантажився ({e})")
        return None
    return stt if stt.engine == name else None


def recognize(stt, name, pcm) -> str:
    if name in ("parakeet", "canary"):         # «сирий» результат моделі, без правил Хомі
        return str(stt.onnx.recognize(stt._f32(pcm), sample_rate=16000, **stt.onnx_opts)).strip()
    return stt.command(pcm)                    # Whisper: з примусовою українською, як у Хомі


def evaluate(cfg, wanted: list[str]):
    from .text import looks_ukrainian
    clips = [(i, load_wav(DIR / f"{i + 1:02d}.wav")) for i in range(len(PHRASES)) if (DIR / f"{i + 1:02d}.wav").exists()]
    if not clips:
        print("Немає записів. Спершу:  .venv\\Scripts\\python -m agent.stt_bench --record")
        return
    base = [n for n in wanted if n in ("parakeet", "canary", "whisper")]
    if "pipeline" in wanted:
        base = list(dict.fromkeys(base + ["parakeet", "canary"]))
    engines = {n: load_engine(cfg, n) for n in base}
    engines = {n: s for n, s in engines.items() if s is not None}

    hyps: dict[str, list[str]] = {n: [] for n in engines}
    secs: dict[str, float] = {n: 0.0 for n in engines}
    for _, pcm in clips:
        for n, stt in engines.items():
            t = time.time()
            hyps[n].append(recognize(stt, n, pcm))
            secs[n] += time.time() - t
    if "pipeline" in wanted and "parakeet" in engines and "canary" in engines:
        hyps["pipeline"] = [p if looks_ukrainian(p) else c for p, c in zip(hyps["parakeet"], hyps["canary"])]
        secs["pipeline"] = 0.0         # час «як зараз» окремо не міряємо: це Parakeet + Canary на частині фраз
    ref_words = sum(len(normalize(PHRASES[i])) for i, _ in clips)

    lines = [f"Записів: {len(clips)} фраз, {ref_words} слів (мова примусово українська, де це можливо)", ""]
    lines.append(f"{'розпізнавач':12s} {'помилок у словах':>17s}  {'не укр.':>7s}  {'ы/э/ъ/ё':>8s}  {'час/фраза':>9s}")
    for n, hs in hyps.items():
        errs = sum(word_errors(PHRASES[i], h) for (i, _), h in zip(clips, hs))
        not_uk = sum(not looks_ukrainian(h) for h in hs)
        ru = sum(any(ch in RUSSIAN_LETTERS for ch in h.lower()) for h in hs)
        t = f"{secs[n] / len(clips):.2f} с" if n != "pipeline" else "—"
        label = "як зараз у Хомі" if n == "pipeline" else n
        lines.append(f"{label:12s} {errs / ref_words:>16.1%}  {not_uk:>7d}  {ru:>8d}  {t:>9s}")
    lines += ["", "=== Фраза за фразою ==="]
    for k, (i, _) in enumerate(clips):
        lines.append(f"\n{i + 1:2d}. {PHRASES[i]}")
        for n in hyps:
            e = word_errors(PHRASES[i], hyps[n][k])
            lines.append(f"    {n:9s} [{e}] «{hyps[n][k]}»")
    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8-sig")
    print(text.split("=== Фраза за фразою ===")[0])
    print("Подробиці по кожній фразі — agent\\stt_bench.txt")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    if "--record" in sys.argv:
        record(cfg)
        return
    wanted = ["parakeet", "canary", "whisper", "pipeline"]
    if "--engines" in sys.argv:
        wanted = sys.argv[sys.argv.index("--engines") + 1].split(",")
    evaluate(cfg, wanted)


if __name__ == "__main__":
    main()
