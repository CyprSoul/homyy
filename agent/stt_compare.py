"""Порівняння розпізнавання на ТВОЄМУ голосі: Canary, Parakeet і Whisper на тих самих записах.

Запуск (Хомі має бути вимкнена):  .venv\\Scripts\\python -m agent.stt_compare
Скажеш 5 фраз — програма покаже, що почув кожен варіант і за скільки. Результат і в agent\\stt_compare.txt.
"""
import sys
import time

from .config import AGENT_DIR, load_config

PROMPTS = ["Скажи будь-яку звичайну фразу, наприклад: «Привіт, як справи?»",
           "Тепер довшу: розкажи, чим займаєшся сьогодні",
           "Спитай щось: «Яка завтра погода в Києві?»",
           "Скажи з паузою посередині: «Я хочу… щоб ти мені нагадала про тренування»",
           "Будь-що на твій вибір"]
lines: list[str] = []


def say(text: str):
    print(text, flush=True)
    lines.append(text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    from .audio import Audio
    from .stt import STT

    engines = {}
    for name in ("canary", "parakeet", "whisper"):
        c = {**cfg, "stt": {**cfg["stt"], "engine": name, "whisper_fallback": False, "fallback_engine": "none", "device": "cpu"}}
        try:
            stt = STT(c)
            if stt.engine == name:
                engines[name] = stt
        except Exception as e:
            say(f"{name}: не завантажився ({e})")
    audio = Audio(cfg)
    clips = []
    for i, prompt in enumerate(PROMPTS, 1):
        print(f"\n[{i}/{len(PROMPTS)}] {prompt}", flush=True)
        audio.drain()
        audio.beep(up=True)
        seg = audio.listen(end_silence_ms=1200, max_seconds=15, start_timeout_s=10)
        if seg is None:
            print("   …нічого не почула, далі")
            continue
        clips.append(seg[0])
        print(f"   ✓ записала ({len(seg[0]) / 16000:.1f} с)")

    say("\n=== Що почув кожен ===")
    totals = {n: 0.0 for n in engines}
    for i, pcm in enumerate(clips, 1):
        say(f"\nФраза {i} ({len(pcm) / 16000:.1f} с):")
        for name, stt in engines.items():
            t = time.time()
            text = stt.command(pcm)
            dt = time.time() - t
            totals[name] += dt
            say(f"  {name:9s} {dt:4.1f} с  «{text}»")
    if clips:
        say("\nСередній час: " + ", ".join(f"{n} {t / len(clips):.1f} с" for n, t in totals.items()))
    (AGENT_DIR / "stt_compare.txt").write_text("\n".join(lines), encoding="utf-8-sig")
    say("\nГотово. Результат: agent\\stt_compare.txt — надішли мені.")


if __name__ == "__main__":
    main()
