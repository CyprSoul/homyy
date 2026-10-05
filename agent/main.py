"""Голосова Хомі: «Хооміі» → «Так?» → твоє питання → відповідь голосом.

Поруч живе віджет-кулька: показує, що Хомі робить, і будить її по кліку.
"""
import os
import random
import socket
import sys
import threading
import time
import traceback

import requests

from .config import AGENT_DIR, load_config
from .text import collapse, greeting, is_noise, is_pause, is_stop, is_wake

LOG_FILE = AGENT_DIR / "homyy.log"


class UI:
    """Пам'ятає поточний стан і передає його сфері (якщо вона є)."""

    def __init__(self, orb=None):
        self.orb = orb
        self.state = "boot"

    def set_state(self, state: str):
        self.state = state
        if self.orb:
            self.orb.set_state(state)


ui = UI()
paused = threading.Event()


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
    ow = cfg.get("openwebui", {})
    if not ow.get("api_key"):
        log("!", "Немає API-ключа Open WebUI — спільна пам'ять вимкнена.")
        return
    try:
        r = requests.get(f"{ow['url']}/api/v1/memories/", timeout=5,
                         headers={"Authorization": f"Bearer {ow['api_key']}"})
        r.raise_for_status()
        log("✓", f"Спільна пам'ять: {len(r.json())} записів")
    except requests.RequestException as e:
        log("✗", f"Спільна пам'ять недоступна: {e}")


def sleep(audio):
    audio.beep(up=False)
    ui.set_state("sleep")
    log("💤", "Сплю. Щоб покликати — «Хооміі» або клік по кульці.")


def _ollama_keep(cfg, keep_alive):
    """keep_alive=0 — вивантажити Gemma з відеокарти (для ігор), інше — завантажити наперед."""
    o = cfg["ollama"]
    try:
        requests.post(f"{o['url']}/api/generate", timeout=120,
                      json={"model": o["model"], "keep_alive": keep_alive,
                            "options": {"num_ctx": o.get("num_ctx", 32768)}})
    except requests.RequestException:
        pass


CFG: dict = {}


def pause(audio):
    paused.set()
    threading.Thread(target=_ollama_keep, args=(CFG, 0), daemon=True).start()
    audio.beep(up=False)
    ui.set_state("paused")
    log("⏸️", "Пауза: не слухаю, відеокарта вільна. Продовжити — клік по сфері або меню.")


def resume():
    paused.clear()
    threading.Thread(target=_ollama_keep, args=(CFG, CFG["ollama"].get("keep_alive", "24h")),
                     daemon=True).start()
    ui.set_state("sleep")
    log("▶️", "Знову слухаю «Хооміі».")


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
        t_stt = time.time()
        text = stt.command(seg[0])
        stt_s = time.time() - t_stt
        if is_noise(text) or is_wake(text, 9.0, 0.0, 2):   # шум або просто повторене «Хомі»
            continue
        log("Ти", f"{text}   [розпізнала за {stt_s:.1f} с]")
        if is_stop(text):
            sleep(audio)
            return
        if is_pause(text):
            pause(audio)
            return
        ui.set_state("think")
        t_llm = time.time()
        try:
            answer = brain.ask(text, on_tool=lambda n, a: log("інструмент", f"{n} {a}"))
        except requests.RequestException as e:
            log("помилка", str(e))
            answer = "Ой, я не можу достукатися до свого мозку. Перевір, будь ласка, чи працює Ollama."
        log("Хомі", f"{answer}   [думала {time.time() - t_llm:.1f} с]")
        speak(speaker, audio, answer)
        audio.beep(up=True)                 # «можеш говорити далі без «Хомі»»
        timeout = float(w.get("follow_up_seconds", 8))


def _feed_levels(orb, audio):
    """20 разів на секунду передає сфері гучність — лише коли Хомі слухає тебе чи говорить,
    щоб уві сні вона не смикалась від кожного звуку (Discord, музика, розмови поруч)."""
    while True:
        orb.set_level(audio.level() if ui.state in ("listen", "speak") else 0.0)
        time.sleep(0.05)


def voice_loop(cfg: dict, wake_click: threading.Event, orb=None):
    wait_for_ollama(cfg)
    check_services(cfg)
    log("…", "завантажую Gemma у відеокарту наперед")
    _ollama_keep(cfg, cfg["ollama"].get("keep_alive", "24h"))

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
        if paused.is_set():
            audio.drain()
            if wake_click.wait(timeout=0.3):      # клік по сфері під час паузи = продовжити
                wake_click.clear()
                resume()
                sleep_state_logged = True
            continue
        seg = audio.listen(end_silence_ms=500, max_seconds=4, interrupt=wake_click)
        if paused.is_set():                       # паузу ввімкнули з меню, поки слухала
            continue
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


_instance_lock = None


def single_instance() -> bool:
    """Лише одна Хомі на ПК: друга копія (наприклад, з автозапуску) тихо виходить."""
    global _instance_lock
    _instance_lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _instance_lock.bind(("127.0.0.1", 47811))
        return True
    except OSError:
        return False


def main():
    global ui
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not single_instance():
        log("!", "Хомі вже запущена (дивись сферу в кутку екрана). Цю копію закриваю.")
        time.sleep(3)
        return
    cfg = load_config()
    CFG.update(cfg)
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

    ui = UI(orb)
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
        elif event == "pause":
            if paused.is_set():
                resume()
            else:
                paused.set()
                threading.Thread(target=_ollama_keep, args=(CFG, 0), daemon=True).start()
                ui.set_state("paused")
                log("⏸️", "Пауза: не слухаю, відеокарта вільна. Продовжити — клік по сфері або меню.")
        elif event == "quit" or not orb.alive():
            log("Хомі", "Вимикаюсь. Бувай!")
            os._exit(0)


if __name__ == "__main__":
    main()
