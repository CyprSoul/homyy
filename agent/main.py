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

    def set_visible(self, visible: bool):
        if self.orb:
            self.orb.set_visible(visible)


ui = UI()
paused = threading.Event()
game_now = threading.Event()        # гра зараз на екрані (ставить спостерігач)
game_mode = False                   # чи Хомі вже перейшла в ігровий режим


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
    ui.set_state("game" if game_mode else "sleep")
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
    if not game_mode:                    # у грі Gemma прокинеться лише на «Хооміі»
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
    try:
        _conversation(cfg, audio, stt, brain, speaker)
    finally:
        if game_mode:                    # після розмови в грі знову звільняємо відеокарту
            threading.Thread(target=_ollama_keep, args=(cfg, 0), daemon=True).start()


def _conversation(cfg, audio, stt, brain, speaker):
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
        if game_mode:
            log("🎮", "Gemma прокидається з ігрового режиму (до ~20 с)")
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


def _watch_games(cfg: dict):
    """Раз на 3 секунди дивиться, чи на екрані гра. Нові повноекранні ігри запам'ятовує сама."""
    from .gamewatch import DEFAULT_IGNORE, classify, foreground, load_learned, remember
    g = cfg.get("game", {})
    if not g.get("enabled", True):
        return
    while True:
        try:
            learned = load_learned()
            games = {x.lower() for x in g.get("processes", [])} | learned["games"]
            ignore = DEFAULT_IGNORE | {x.lower() for x in g.get("ignore", [])} | learned["ignore"]
            exe, full = foreground()
            if classify(exe, full, games, ignore):
                if exe and exe.lower() not in games and remember(exe, True):
                    log("🎮", f"Запам'ятала нову гру: {exe}")
                game_now.set()
            else:
                game_now.clear()
        except Exception:
            pass
        time.sleep(3)


def _hotkey(wake_click: threading.Event):
    """Ctrl+Alt+H — покликати Хомі клавішами (працює й у грі, коли голосовий виклик вимкнено)."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, VK_H, WM_HOTKEY = 0x1, 0x2, 0x4000, 0x48, 0x312
    if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL | MOD_NOREPEAT, VK_H):
        log("!", "Не вдалося зареєструвати Ctrl+Alt+H (зайнято іншою програмою).")
        return
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            wake_click.set()


def enter_game_mode(cfg, stt):
    global game_mode
    from .gamewatch import set_low_priority
    game_mode = True
    if cfg.get("game", {}).get("voice_wake", False):
        log("🎮", "Гра! Звільняю відеокарту й процесор, чекаю тихо на «Хооміі».")
    else:
        log("🎮", "Гра! Хомі повністю спить: мікрофон не слухаю, відеокарта вільна. Покликати — Ctrl+Alt+H.")
    _ollama_keep(cfg, 0)
    stt.release_gpu()
    set_low_priority(True)
    ui.set_state("game")                 # сфера стає напівпрозорим джойстиком, крізь який клікається


def exit_game_mode(cfg, stt):
    global game_mode
    from .gamewatch import set_low_priority
    game_mode = False
    log("🎮", "Гру закрито — повертаюсь у повну силу.")
    set_low_priority(False)
    if cfg["stt"].get("device", "auto") in ("auto", "cuda"):
        stt.load_gpu()
    _ollama_keep(cfg, cfg["ollama"].get("keep_alive", "24h"))
    ui.set_state("sleep")


def _feed_levels(orb, audio):
    """20 разів на секунду передає сфері гучність — лише коли Хомі слухає тебе чи говорить,
    щоб уві сні вона не смикалась від кожного звуку (Discord, музика, розмови поруч)."""
    while True:
        orb.set_level(audio.level() if ui.state in ("listen", "speak") else 0.0)
        time.sleep(0.2 if ui.state == "game" else 0)
        time.sleep(0.05)


def voice_loop(cfg: dict, wake_click: threading.Event, orb=None):
    wait_for_ollama(cfg)
    check_services(cfg)
    # Порядок важливий: спершу звільняємо відеокарту, потім кладемо туди Whisper, і лише потім
    # Gemma — тоді Ollama бачить, скільки місця реально лишилось, і не «переповнює» відеопам'ять
    # (інакше Windows виносить частину в звичайну пам'ять і відповідь іде хвилину).
    _ollama_keep(cfg, 0)

    from .audio import Audio
    from .brain import Brain
    from .stt import STT
    from .tts import Speaker

    stt = STT(cfg)
    log("…", "завантажую Gemma у відеокарту наперед")
    _ollama_keep(cfg, cfg["ollama"].get("keep_alive", "24h"))
    audio = Audio(cfg)
    brain = Brain(cfg)
    speaker = Speaker(cfg, audio)

    def remind(text: str):
        log("⏰", text)
        audio.beep(up=True)
        prev = ui.state
        speak(speaker, audio, text)
        ui.set_state(prev)
    brain.tools.on_reminder = remind

    if cfg.get("telegram", {}).get("token"):
        from .telegram_bot import TelegramBot
        TelegramBot(cfg, Brain(cfg), stt, log, is_gaming=lambda: game_mode).start()
    if orb is not None:
        threading.Thread(target=_feed_levels, args=(orb, audio), daemon=True).start()
    threading.Thread(target=_watch_games, args=(cfg,), daemon=True).start()
    threading.Thread(target=_hotkey, args=(wake_click,), daemon=True).start()
    w = cfg["wake"]
    min_s, max_words = float(w.get("min_seconds", 0.6)), int(w.get("max_words", 3))
    from .wakeword import Features, WakeModel
    detector = WakeModel.load()
    features = Features() if detector else None
    log("👂", "Персональний детектор «Хооміі» увімкнено" if detector else
        "Персонального детектора ще немає — навчи: python -m agent.record_wake")

    log("Хомі", "Готова! Поклич мене: «Хооміі». Вийти — Ctrl+C або правий клік по кульці.")
    if cfg.get("ui", {}).get("greet", True):
        speak(speaker, audio, greeting(cfg["user"]["name"], time.localtime().tm_hour, random.randrange(10)))
    sleep_state_logged = False
    while True:
        if not sleep_state_logged:
            ui.set_state("game" if game_mode else "sleep")
            log("💤", "Сплю. Щоб покликати — «Хооміі» або клік по кульці.")
            sleep_state_logged = True
        if paused.is_set():
            audio.drain()
            if wake_click.wait(timeout=0.3):      # клік по сфері під час паузи = продовжити
                wake_click.clear()
                resume()
                sleep_state_logged = True
            continue
        if game_now.is_set() != game_mode:
            (enter_game_mode if game_now.is_set() else exit_game_mode)(cfg, stt)
        if game_mode and not cfg.get("game", {}).get("voice_wake", False):
            audio.drain()                         # у грі нічого не розпізнаємо — нуль навантаження
            if wake_click.wait(timeout=0.5):
                wake_click.clear()
                log("почула", "Ctrl+Alt+H")
                conversation(cfg, audio, stt, brain, speaker)
            continue
        seg = audio.listen(end_silence_ms=500, max_seconds=4,
                           interrupt=lambda: wake_click.is_set() or game_now.is_set() != game_mode)
        if paused.is_set():                       # паузу ввімкнули з меню, поки слухала
            continue
        if seg == "interrupt":
            if wake_click.is_set():
                wake_click.clear()
                log("почула", "клік по кульці")
                conversation(cfg, audio, stt, brain, speaker)
            continue
        pcm, speech_s = seg
        if speech_s < min_s * 0.8:          # явно коротке — навіть не розпізнаємо
            continue
        if detector:
            score = detector.score(features.vector(pcm))
            if score < detector.threshold * 0.6:      # зовсім не схоже на твоє «Хооміі» — далі не дивимось
                continue
            heard = stt.wake(pcm)
            # обидві перевірки: звучить як твоє «Хооміі» І текст схожий на «Хомі»
            woke = score >= detector.threshold and (is_wake(heard, speech_s, 0.0, max_words) or score >= 0.97)
            log("почула" if woke else "не те", f"«{heard}» ({speech_s:.1f} с, схожість {score:.2f})")
        else:
            heard = stt.wake(pcm)
            woke = is_wake(heard, speech_s, min_s, max_words)
            if woke:
                log("почула", f"«{heard}» ({speech_s:.1f} с)")
            elif "м" in collapse(heard):
                log("не те", f"«{heard}» ({speech_s:.1f} с)")   # підказка для налаштування min_seconds
        if woke:
            conversation(cfg, audio, stt, brain, speaker)


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
