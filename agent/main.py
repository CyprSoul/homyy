"""Голосова Хомі: «Хоооуммміііі» → сигнал → твоє питання → відповідь голосом."""
import sys
import time

import requests

from .config import load_config
from .text import collapse, is_noise, is_stop, is_wake


def log(who: str, text: str):
    print(f"[{time.strftime('%H:%M:%S')}] {who}: {text}", flush=True)


def check_services(cfg: dict):
    checks = {"Ollama": cfg["ollama"]["url"] + "/api/tags",
              "Голос (edge-tts)": cfg["tts"]["url"].rsplit("/v1/", 1)[0] + "/",
              "Пошук (SearXNG)": cfg["search"]["url"]}
    for name, url in checks.items():
        try:
            requests.get(url, timeout=3)
            log("✓", name)
        except requests.RequestException:
            log("✗", f"{name} недоступний ({url}). Запусти Docker / Ollama.")
    if not cfg.get("openwebui", {}).get("api_key"):
        log("!", "Немає API-ключа Open WebUI — спільна пам'ять вимкнена.")


def conversation(cfg, audio, stt, brain, speaker):
    w = cfg["wake"]
    audio.beep(up=True)
    timeout = float(w.get("follow_up_seconds", 8))
    while True:
        seg = audio.listen(end_silence_ms=900, max_seconds=25, start_timeout_s=timeout)
        if seg is None:
            audio.beep(up=False)
            log("Хомі", "(слухаю «Хоооуммміііі» далі)")
            return
        text = stt.command(seg[0])
        if is_noise(text) or is_wake(text, 9.0, 0.0, 2):   # шум або просто повторене «Хомі»
            continue
        log("Ти", text)
        if is_stop(text):
            audio.beep(up=False)
            return
        try:
            answer = brain.ask(text, on_tool=lambda n, a: log("інструмент", f"{n} {a}"))
        except requests.RequestException as e:
            log("помилка", str(e))
            answer = "Ой, я не можу достукатися до свого мозку. Перевір, будь ласка, чи працює Ollama."
        log("Хомі", answer)
        try:
            speaker.say(answer)
        except requests.RequestException as e:
            log("помилка голосу", str(e))
        timeout = float(w.get("follow_up_seconds", 8))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    check_services(cfg)

    from .audio import Audio
    from .brain import Brain
    from .stt import STT
    from .tts import Speaker

    stt = STT(cfg)
    audio = Audio(cfg)
    brain = Brain(cfg)
    speaker = Speaker(cfg, audio)
    w = cfg["wake"]
    min_s, max_words = float(w.get("min_seconds", 1.0)), int(w.get("max_words", 3))

    log("Хомі", "Готова! Скажи протяжно «Хоооуммміііі». Вийти — Ctrl+C.")
    while True:
        seg = audio.listen(end_silence_ms=500, max_seconds=4)
        pcm, speech_s = seg
        if speech_s < min_s * 0.8:          # явно коротке — навіть не розпізнаємо
            continue
        heard = stt.wake(pcm)
        if is_wake(heard, speech_s, min_s, max_words):
            log("почула", f"«{heard}» ({speech_s:.1f} с)")
            conversation(cfg, audio, stt, brain, speaker)
        elif "м" in collapse(heard):
            log("не те", f"«{heard}» ({speech_s:.1f} с)")   # підказка для налаштування min_seconds


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nБувай! 👋")
