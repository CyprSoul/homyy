"""Замір швидкості Хомі однією командою — без мікрофона й без розмов.

Запуск (Хомі має бути вимкнена):  .venv\\Scripts\\python -m agent.bench
                 з порівнянням розпізнавання на відеокарті:  ... -m agent.bench --gpu
                 інша модель (config.toml не змінюється):     ... -m agent.bench --gpu --model gemma4:12b

Що робить: Марічка озвучує фразу → Whisper її розпізнає → Gemma відповідає → Марічка озвучує
перше речення відповіді. Кожен етап — 3 рази, у кінці таблиця. Результат також у agent\\bench.txt.
"""
import sys
import time

import numpy as np
import requests

from .config import AGENT_DIR, load_config, ollama_options

QUESTIONS = ["Привіт, Хомі, як твої справи сьогодні?",
             "Порадь, що подивитися ввечері.",
             "Скільки буде сімнадцять помножити на три?"]
lines: list[str] = []


def say(*parts):
    text = " ".join(str(p) for p in parts)
    print(text, flush=True)
    lines.append(text)


def gpu_share(cfg) -> str:
    try:
        models = requests.get(cfg["ollama"]["url"] + "/api/ps", timeout=5).json().get("models", [])
    except requests.RequestException:
        return "?"
    for m in models:
        if m.get("size"):
            return f"{100 * m.get('size_vram', 0) / m['size']:.0f}% у відеокарті"
    return "Gemma не завантажена"


def to_16k(pcm24: np.ndarray) -> np.ndarray:
    x = pcm24.astype(np.float32)
    idx = np.arange(int(len(x) * 16000 / 24000)) * 24000 / 16000
    return np.interp(idx, np.arange(len(x)), x).astype(np.int16)


def run_round(label, cfg, stt, brain, speaker):
    say(f"\n=== {label} ===")
    rows = []
    for q in QUESTIONS:
        pcm = to_16k(speaker._synth(q))
        t = time.time()
        heard = stt.command(pcm)
        t_stt = time.time() - t
        t = time.time()
        brain.history = []
        answer = brain.ask(heard or q)
        t_llm = time.time() - t
        first = speaker_first_chunk(answer)
        t = time.time()
        speaker._synth(first)
        t_tts = time.time() - t
        rows.append((t_stt, t_llm, t_tts))
        say(f"  «{heard}» → «{answer[:70]}»")
        say(f"     розпізнала {t_stt:.1f} с | думала {t_llm:.1f} с | голос {t_tts:.1f} с | "
            f"разом {t_stt + t_llm + t_tts:.1f} с")
        for st in brain.stats:
            say(f"     Ollama: {st}")
    avg = np.mean(rows, axis=0)
    say(f"  СЕРЕДНЄ: розпізнала {avg[0]:.1f} | думала {avg[1]:.1f} | голос {avg[2]:.1f} | "
        f"РАЗОМ {avg.sum():.1f} с   (Gemma: {gpu_share(cfg)})")


def speaker_first_chunk(answer: str) -> str:
    from .text import clean_for_speech, split_sentences
    parts = split_sentences(clean_for_speech(answer))
    return parts[0] if parts else answer


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    o, s = cfg["ollama"], cfg["stt"]
    if "--model" in sys.argv:                      # спробувати іншу модель, не чіпаючи config.toml
        o["model"] = sys.argv[sys.argv.index("--model") + 1]
        cfg["ollama"]["keep_alive"] = "5m"
    say("Налаштування, з якими міряю:")
    say(f"  Gemma: {o['model']}, {ollama_options(cfg)}")
    say(f"  Розпізнавання: {s['model']} на {s.get('device', 'auto')}, потоків {s.get('cpu_threads')}")
    say(f"  Голос: {cfg['tts']['voice']}")

    from .brain import Brain
    from .stt import STT
    from .tts import Speaker

    # той самий порядок, що й у Хомі: вивантажити Gemma → Whisper → Gemma
    requests.post(o["url"] + "/api/generate", json={"model": o["model"], "keep_alive": 0}, timeout=60)
    stt = STT(cfg)
    t = time.time()
    requests.post(o["url"] + "/api/generate", timeout=300,
                  json={"model": o["model"], "keep_alive": o.get("keep_alive", "24h"),
                        "options": ollama_options(cfg)})
    say(f"Gemma завантажилась за {time.time() - t:.0f} с ({gpu_share(cfg)})")
    brain, speaker = Brain(cfg), Speaker(cfg, audio=None)
    speaker._synth("Привіт.")                      # прогрів голосу
    run_round("Як налаштовано зараз", cfg, stt, brain, speaker)

    if "--gpu" in sys.argv and stt.gpu_model is None:
        # чесне порівняння: як у Хомі — Gemma вивантажити, Whisper на відеокарту, потім Gemma
        requests.post(o["url"] + "/api/generate", json={"model": o["model"], "keep_alive": 0}, timeout=60)
        time.sleep(2)
        if stt.load_gpu():
            requests.post(o["url"] + "/api/generate", timeout=300,
                          json={"model": o["model"], "keep_alive": o.get("keep_alive", "24h"),
                                "options": ollama_options(cfg)})
            run_round("Розпізнавання на відеокарті", cfg, stt, brain, speaker)

    # з BOM — щоб PowerShell (type) показав українські букви, а не «РќР°Р»...»
    (AGENT_DIR / "bench.txt").write_text("\n".join(lines), encoding="utf-8-sig")
    say("\nГотово. Результат збережено в agent\\bench.txt — надішли його мені.")


if __name__ == "__main__":
    main()
