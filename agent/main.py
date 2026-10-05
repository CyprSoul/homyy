"""Голосова Хомі: «Хооміі» → «Так?» → твоє питання → відповідь голосом.

Поруч живе віджет-кулька: показує, що Хомі робить, і будить її по кліку.
"""
import os
import random
import sys
import threading
import time
import traceback

import requests

from .config import AGENT_DIR, load_config
from .text import collapse, greeting, is_noise, is_stop, is_wake

LOG_FILE = AGENT_DIR / "homyy.log"


class NoUI:
    def set_state(self, state: str):
        pass

    def set_level(self, level: float):
        pass


ui = NoUI()


def log(who: str, text: str):
    line = f"[{time.strftime('%H:%M:%S')}] {who}: {text}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d')} {line}\n")
    except OSError:
        pass


def wait_for_ollama(cfg: dict, max_wait_s: int = 300):
    """Після увімкнення ПК Ollama й Docker стартують не одразу — чекаємо їх."""
    url = cfg["ollama"]["url"] + "/api/tags"
    start = time.time()
    while time.time() - start < max_wait_s:
        try:
            requests.get(url, timeout=3)
            return
        except requests.RequestException:
            log("…", "чекаю, поки запуститься Ollama")
            time.sleep(10)


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


def sleep(audio):
    audio.beep(up=False)
    ui.set_state("sleep")
    log("💤", "Сплю. Щоб покликати — «Хооміі» або клік по кульці.")


def speak(speaker, audio, text: str):
    ui.set_state("speak")
    try:
        speaker.say(text)
    except requests.RequestException as e:
        log("помилка голосу", str(e))
        audio.beep(up=True)


def conversation(cfg, audio, stt, brain, speaker):
    w = cfg["wake"]
    ui.set_state("speak")
    try:
        speaker.say_cached("Так?")          # чітко чути: Хомі прокинулась і слухає
    except requests.RequestException:
        audio.beep(up=True)
    timeout = float(w.get("follow_up_seconds", 8))
    while True:
        ui.set_state("listen")
        log("🎙️", f"Слухаю… (говори, у тебе {timeout:.0f} с)")
        seg = audio.listen(end_silence_ms=900, max_seconds=25, start_timeout_s=timeout)
        if seg is None:
            sleep(audio)
            return
        ui.set_state("hear")
        text = stt.command(seg[0])
        if is_noise(text) or is_wake(text, 9.0, 0.0, 2):   # шум або просто повторене «Хомі»
            continue
        log("Ти", text)
        if is_stop(text):
            sleep(audio)
            return
        ui.set_state("think")
        try:
            answer = brain.ask(text, on_tool=lambda n, a: log("інструмент", f"{n} {a}"))
        except requests.RequestException as e:
            log("помилка", str(e))
            answer = "Ой, я не можу достукатися до свого мозку. Перевір, будь ласка, чи працює Ollama."
        log("Хомі", answer)
        speak(speaker, audio, answer)
        audio.beep(up=True)                 # «можеш говорити далі без «Хомі»»
        timeout = float(w.get("follow_up_seconds", 8))


def _feed_levels(orb, audio):
    """20 разів на секунду передає сфері гучність, щоб вона «жила» в такт голосу."""
    while True:
        orb.set_level(audio.level())
        time.sleep(0.05)


def voice_loop(cfg: dict, wake_click: threading.Event, orb=None):
    wait_for_ollama(cfg)
    check_services(cfg)

    from .audio import Audio
    from .brain import Brain
    from .stt import STT
    from .tts import Speaker

    stt = STT(cfg)
    audio = Audio(cfg)
    brain = Brain(cfg)
    speaker = Speaker(cfg, audio)
    if orb is not None:
        threading.Thread(target=_feed_levels, args=(orb, audio), daemon=True).start()
    w = cfg["wake"]
    min_s, max_words = float(w.get("min_seconds", 0.6)), int(w.get("max_words", 3))

    log("Хомі", "Готова! Поклич мене: «Хооміі». Вийти — Ctrl+C або правий клік по кульці.")
    if cfg.get("ui", {}).get("greet", True):
        speak(speaker, audio, greeting(cfg["user"]["name"], time.localtime().tm_hour, random.randrange(10)))
    sleep_state_logged = False
    while True:
        if not sleep_state_logged:
            ui.set_state("sleep")
            log("💤", "Сплю. Щоб покликати — «Хооміі» або клік по кульці.")
            sleep_state_logged = True
        seg = audio.listen(end_silence_ms=500, max_seconds=4, interrupt=wake_click)
        if seg == "interrupt":
            log("почула", "клік по кульці")
            conversation(cfg, audio, stt, brain, speaker)
            continue
        pcm, speech_s = seg
        if speech_s < min_s * 0.8:          # явно коротке — навіть не розпізнаємо
            continue
        heard = stt.wake(pcm)
        if is_wake(heard, speech_s, min_s, max_words):
            log("почула", f"«{heard}» ({speech_s:.1f} с)")
            conversation(cfg, audio, stt, brain, speaker)
        elif "м" in collapse(heard):
            log("не те", f"«{heard}» ({speech_s:.1f} с)")   # підказка для налаштування min_seconds


def main():
    global ui
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    wake_click = threading.Event()

    if not cfg.get("ui", {}).get("widget", True):
        voice_loop(cfg, wake_click)
        return

    try:
        from .orb import OrbClient
        orb = OrbClient(position=cfg.get("ui", {}).get("position", "bottom-right"))
    except Exception as e:   # немає Qt — працюємо без сфери
        log("!", f"Сфера не запустилася ({e}), працюю без неї.")
        voice_loop(cfg, wake_click)
        return

    ui = orb
    threading.Thread(target=_orb_events, args=(orb, wake_click), daemon=True).start()
    try:
        voice_loop(cfg, wake_click, orb)
    except Exception:
        ui.set_state("error")               # сфера червоніє — видно, що щось зламалось
        log("помилка", traceback.format_exc())
        time.sleep(5)
        raise


def _orb_events(orb, wake_click: threading.Event):
    """Клік по сфері — покликати Хомі; «Вимкнути» в меню — вийти."""
    while True:
        event = orb.next_event(timeout=1.0)
        if event == "click":
            wake_click.set()
        elif event == "quit" or not orb.alive():
            log("Хомі", "Вимикаюсь. Бувай!")
            os._exit(0)


if __name__ == "__main__":
    main()
