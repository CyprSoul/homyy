"""Голосова Хомі: «Хооміі» → «Так?» → твоє питання → відповідь голосом.

Поруч живе віджет-кулька: показує, що Хомі робить, і будить її по кліку.
"""
import os
import random
import re
import socket
from urllib.parse import urlparse
import sys
import threading
import time
import traceback

import numpy as np
import requests

from .config import AGENT_DIR, load_config, ollama_options
from .skills import SkillBook
from .text import (collapse, greeting, interrupt_request, is_new_topic, is_noise, is_pause, is_stop,
                   is_no, is_wake, is_yes, media_intent, split_wake, unfinished, click_intent,
                   wants_selection, window_intent, foreign_speech, folder_intent, fix_command)

LOG_FILE = AGENT_DIR / "homyy.log"
SKILLS = SkillBook()


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


_HEADLESS = False


def log(who: str, text: str):
    line = f"[{time.strftime('%H:%M:%S')}] {who}: {text}"
    if not _HEADLESS:                 # без вікна print і так іде в журнал — не дублюємо
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
              "Голос": cfg["tts"]["url"].rsplit("/v1/", 1)[0] + "/",
              "Запасний голос": cfg["tts"].get("fallback", {}).get("url", cfg["tts"]["url"]).rsplit("/v1/", 1)[0] + "/",
              "Пошук (SearXNG)": cfg["search"]["url"]}
    for name, url in checks.items():
        # Досить того, що порт відповідає: деякі сервери (StyleTTS2) довго думають над «/».
        u = urlparse(url)
        try:
            socket.create_connection((u.hostname, u.port or (443 if u.scheme == "https" else 80)), timeout=3).close()
            log("✓", name)
        except OSError:
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
                            "options": ollama_options(cfg)})
    except requests.RequestException:
        pass


READY_PHRASES = ["Все, я готова!", "Я готова, можеш питати.", "Готова до роботи!", "Все, я в строю!"]

CFG: dict = {}
BRAIN: list = []                    # голосовий «мозок» — щоб меню сфери могло почати нову тему


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


def conversation(cfg, audio, stt, brain, speaker, first=None):
    try:
        _conversation(cfg, audio, stt, brain, speaker, first)
    finally:
        if game_mode:                    # після розмови в грі знову звільняємо відеокарту
            threading.Thread(target=_ollama_keep, args=(cfg, 0), daemon=True).start()


def _hear(cfg, audio, stt, timeout: float, first=None):
    """Слухає фразу до кінця. Повертає (текст, коли договорив, скільки розпізнавала) або None.

    Якщо фраза звучить незакінченою («я займаюся тим, що…») — чекає продовження й
    розпізнає все разом: розпізнавання займає десяті частки секунди, тож це майже безкоштовно.
    first = (звук, текст) — фраза вже почута разом із «Хомі» («Хомі, я хочу…»): лише дослухаємо.
    """
    w = cfg["wake"]
    silence = int(w.get("command_silence_ms", 800))

    def recognize(pcm):
        text = stt.command(pcm)
        return split_wake(text) or text if first is not None else text

    if first is not None:
        pcm, t_said = first[0], time.time()
        text, stt_s = first[1], 0.0
    else:
        seg = audio.listen(end_silence_ms=silence, max_seconds=25, start_timeout_s=timeout)
        if seg is None:
            return None
        pcm, t_said = seg[0], time.time()
        ui.set_state("hear")
        t = time.time()
        text = recognize(pcm)
        stt_s = time.time() - t
    for _ in range(4):
        wait = unfinished(text)
        if not wait:
            break
        log("…", f"«{text}» — схоже, ти ще не договорив, чекаю {wait:.1f} с")
        ui.set_state("listen")
        more = audio.listen(end_silence_ms=silence, max_seconds=25, start_timeout_s=wait)
        if more is None:
            break
        pcm, t_said = np.concatenate([pcm, more[0]]), time.time()
        ui.set_state("hear")
        t = time.time()
        text = recognize(pcm)
        stt_s = time.time() - t
    return text, t_said, stt_s


def speak_listening(cfg, speaker, audio, stt, text: str, asked: str = ""):
    """Говорить і водночас слухає, чи ти її не перебиваєш. Два способи:
    1) заговорив поверх неї (мікрофон помітно гучніший за луну її голосу) — замовкає й слухає;
    2) почула «стоп», «почекай», «Хомі…» або «стоп, а яка погода?».

    Повертає None — договорила; "" — перебили, слухати далі; інакше — нове питання після «стоп».
    """
    if not cfg["wake"].get("barge_in", True):
        speak(speaker, audio, text)
        return None
    done, result = threading.Event(), {}

    def stop_now():
        return done.is_set() or audio.barged.is_set()

    def monitor():
        while not stop_now():
            seg = audio.listen(end_silence_ms=400, max_seconds=4, start_timeout_s=0.3, abort=stop_now)
            if not isinstance(seg, tuple) or stop_now():
                continue
            # тихе (луна з навушників, шум) і коротке — не ти; на такому розпізнавач вигадує фрази
            if seg[1] < 0.6 or (hasattr(audio, "loud_enough") and not audio.loud_enough(seg[0])):
                continue
            heard = stt.command(seg[0], fallback=False)
            if not heard:
                continue
            req = interrupt_request(heard, text)
            if req is not None:
                result["req"] = req
                log("✋", f"перебив словом: «{heard}»")
                audio.stop_playback()
                return
            if foreign_speech(heard, text):
                # ти говориш поверх неї (не луна її голосу) — замовкає й слухає. Якщо почав одразу
                # після її першого речення — найімовірніше, ти просто договорюєш попередню думку.
                early = time.time() - started < 8
                result["req"] = f"{asked} {heard}".strip() if early and asked else heard
                log("✋", f"говориш поверх мене: «{heard}» — замовкаю")
                audio.stop_playback()
                return
            log("👂", f"під час мови чую: «{heard}»")     # луна її голосу чи щось інше — для налаштування

    started = time.time()
    if hasattr(audio, "arm_barge_in"):
        audio.arm_barge_in(True)
    t = threading.Thread(target=monitor, daemon=True)
    t.start()
    try:
        speak(speaker, audio, text)
    finally:
        done.set()
        if hasattr(audio, "arm_barge_in"):
            if audio.barged.is_set() and "req" not in result:
                result["req"] = ""
                log("✋", "перебив голосом — замовкаю й слухаю")
            audio.arm_barge_in(False)
        t.join(timeout=3)
    return result.get("req")


def ask_while_listening(cfg, audio, stt, brain, text: str):
    """Gemma думає, а Хомі тим часом далі слухає. Якщо ти продовжив говорити (просто задумався
    посеред думки) — її відповідь викидається, і вона дослуховує тебе до кінця.

    Повертає (None, відповідь) або (новий повний текст, None).
    """
    snapshot = list(brain.history)
    box: dict = {}

    def work():
        try:
            def on_tool(n, a):
                log("інструмент", f"{n} {a}")
                if n in ("web_search", "search_on_site", "find_file", "look_at_screen"):
                    ui.set_state("search")       # сфера показує, що Хомі шукає
            box["answer"] = brain.ask(text, on_tool=on_tool)
        except Exception as e:      # noqa: BLE001 — передаємо далі в головний потік
            box["error"] = e

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    silence = int(cfg["wake"].get("command_silence_ms", 800))
    while worker.is_alive():
        seg = audio.listen(end_silence_ms=silence, max_seconds=25, start_timeout_s=0.2,
                           abort=lambda: not worker.is_alive())
        if isinstance(seg, tuple):
            if hasattr(audio, "loud_enough") and not audio.loud_enough(seg[0]):
                continue
            extra = stt.command(seg[0], fallback=False)
            if not extra or is_noise(extra):
                continue                           # шум — хай Gemma спокійно договорює
            worker.join()
            brain.history = snapshot               # цієї відповіді наче й не було
            log("✋", f"ти ще говориш («{extra}») — не відповідаю, слухаю далі")
            return f"{text} {extra}".strip(), None
    if "error" in box:
        raise box["error"]
    return None, box.get("answer", "")


def _conversation(cfg, audio, stt, brain, speaker, first=None):
    w = cfg["wake"]
    if first is None:
        ui.set_state("speak")
        try:
            speaker.say_cached("Так?")      # чітко чути: Хомі прокинулась і слухає
        except requests.RequestException:
            audio.beep(up=True)
    timeout = float(w.get("follow_up_seconds", 8))
    pending = None                          # питання, сказане одразу після «стоп»
    announce = True
    while True:
        if pending:
            text, t_said, stt_s, pending = pending, time.time(), 0.0, None
        else:
            ui.set_state("listen")
            if announce and first is None:
                log("🎙️", f"Слухаю… (говори, у тебе {timeout:.0f} с)")
            heard = _hear(cfg, audio, stt, timeout, first)
            first = None
            if heard is None:
                sleep(audio)
                return
            text, t_said, stt_s = heard
            text = fix_command(text)
            if is_noise(text) or is_wake(text, 9.0, 0.0, 2):   # шум або просто повторене «Хомі»
                announce = False
                continue
        announce = True
        engine = f", {stt.last_engine}" if getattr(stt, "last_engine", "") else ""
        log("Ти", f"{text}   [розпізнала за {stt_s:.1f} с{engine}]")
        if is_stop(text):
            sleep(audio)
            return
        if is_pause(text):
            pause(audio)
            return
        if is_new_topic(text):
            brain.history = []
            log("🧹", "Нова тема — попередню розмову забула (пам'ять про тебе лишається).")
            speak(speaker, audio, "Добре, нова тема. Слухаю.")
            audio.beep(up=True)
            continue
        ui.set_state("think")
        if game_mode:
            log("🎮", "Gemma прокидається з ігрового режиму (до ~20 с)")
        t_llm = time.time()
        try:
            intent = media_intent(text)
            awaiting, brain.tools.awaiting = brain.tools.awaiting, None
            if awaiting and is_yes(text):   # «Закрити Discord?» → «так» — виконуємо одразу, без Gemma
                brain.tools.last_user_text = text
                log("інструмент", f"{awaiting[0]} {awaiting[1]} (підтверджено)")
                answer = brain.direct(text, awaiting[0], {**awaiting[1], "confirmed": True})
            elif awaiting and is_no(text):
                brain.tools.pending = None
                answer = brain.direct_reply(text, "Добре, не роблю.")
            elif intent:                      # «постав на паузу» — одразу, без Gemma
                log("інструмент", f"media {{'action': '{intent}'}} (швидка команда)")
                answer = brain.direct(text, "media", {"action": intent, "times": 3 if "volume" in intent else 1})
            elif window_intent(text):        # «згорни термінал», «перейди в дискорд» — одразу
                action, target = window_intent(text)
                log("інструмент", f"window {{'action': '{action}', 'name': '{target}'}} (швидка команда)")
                answer = brain.direct(text, "window", {"action": action, "name": target})
            elif folder_intent(text):        # «що в папці Games», «відкрий папку …» — одразу
                tool, target = folder_intent(text)
                log("інструмент", f"{tool} {{'name': '{target}'}} (швидка команда)")
                answer = brain.direct(text, tool, {"name": target})
                if tool == "list_folder" and not answer.startswith("Не знайшла"):
                    answer = brain.ask(f"{text}\n\n(Ось що в папці — коротко перекажи голосом:)\n{answer}")
            elif wants_selection(text):      # «переклади виділене» — беремо текст, а не знімок екрана
                from .windows import selected_text
                sel = selected_text()
                log("інструмент", f"selected_text → {len(sel)} символів")
                if sel:
                    answer = brain.ask(f"{text}\n\n(Виділений текст, з яким треба працювати:)\n{sel[:6000]}",
                                       on_tool=lambda n, a: log("інструмент", f"{n} {a}"))
                else:
                    answer = brain.direct_reply(text, "Не бачу виділеного тексту. Виділи його мишкою й скажи ще раз.")
            elif click_intent(text):         # «натисни на …» — одразу, без Gemma
                target = click_intent(text)
                log("інструмент", f"click_on_screen {{'text': '{target}'}} (швидка команда)")
                brain.tools.last_user_text = text
                answer = brain.direct(text, "click_on_screen", {"text": target})
            elif re.match(r"^(?:хомі,?\s*)?(?:забудь|розучись),? як", text.strip(), re.I):
                ok = SKILLS.forget(text)
                answer = brain.direct_reply(text, "Добре, забула цю навичку." if ok else "Такої навички в мене немає.")
            elif (skill := SKILLS.match(text)):
                # вивчена навичка: повторюємо ті самі кроки одразу, без Gemma
                log("⚡", f"навичка «{skill['phrase']}» → {[c['name'] for c in skill['calls']]}")
                results = [brain.tools.call(c["name"], c["arguments"]) for c in skill["calls"]]
                answer = brain.direct_reply(text, " ".join(r for r in results if r)[:300])
            else:
                more, answer = ask_while_listening(cfg, audio, stt, brain, text)
                if more:                     # ти ще говорив, поки вона думала — відповідь скасована
                    pending = more
                    continue
                if SKILLS.observe(text, brain.last_calls, brain.last_results):
                    log("🧠", f"навчилась: «{text}» → {[c['name'] for c in brain.last_calls]}")
                    answer += " До речі, я запам'ятала, як це робиться, — наступного разу зроблю одразу."
        except requests.RequestException as e:
            log("помилка", str(e))
            answer = "Ой, я не можу достукатися до свого мозку. Перевір, будь ласка, чи працює Ollama."
        log("Хомі", f"{answer}   [думала {time.time() - t_llm:.1f} с]")
        for st in brain.stats:
            log("⏱", st)
        speaker.first_audio_at = None
        t_voice = time.time()
        req = speak_listening(cfg, speaker, audio, stt, answer, asked=text)
        if speaker.first_audio_at:
            log("⏱", f"від кінця твоєї фрази до голосу {speaker.first_audio_at - t_said:.1f} с "
                     f"(розпізнала {stt_s:.1f}, думала {t_voice - t_llm:.1f}, "
                     f"голос {speaker.first_audio_at - t_voice:.1f})")
        if req:
            pending = req                   # «стоп, а яка погода?» — одразу відповідаємо на нове
            continue
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
    if stt.parakeet is None and cfg["stt"].get("device", "auto") in ("auto", "cuda"):
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
    s = cfg["stt"]
    if s.get("engine", "whisper") == "whisper" and s.get("device", "auto") in ("auto", "cuda"):
        _ollama_keep(cfg, 0)        # Whisper піде на відеокарту — Gemma вантажимо вже після нього
    # Інакше (Parakeet/Canary на процесорі) Gemma, що вже в пам'яті після минулого запуску, лишається —
    # перезапуск Хомі займає секунди, а не ~25 с.

    from .audio import Audio
    from .brain import Brain
    from .stt import STT
    from .tts import Speaker

    stt = STT(cfg)
    # Gemma вантажиться у фоні (~20 с): Хомі вже слухає й вітається, а питання просто трохи зачекає.
    log("…", "завантажую Gemma у відеокарту у фоні")
    voice = {}                           # тут з'явиться голос, коли він буде готовий

    def _preload():
        t = time.time()
        _ollama_keep(cfg, cfg["ollama"].get("keep_alive", "24h"))
        took = time.time() - t
        log("✓", f"Gemma готова ({took:.0f} с)")
        # Сказати вголос, що вже можна питати — лише якщо довелося чекати й Хомі зараз нічим не зайнята
        if took > 3 and cfg.get("ui", {}).get("announce_ready", True):
            ready_voice.wait(60)
            if ui.state == "sleep" and not game_mode and not paused.is_set():
                speak(voice["speaker"], voice["audio"], random.choice(READY_PHRASES))
                ui.set_state("sleep")
    ready_voice = threading.Event()
    threading.Thread(target=_preload, daemon=True).start()
    audio = Audio(cfg)
    brain = Brain(cfg)
    BRAIN.append(brain)
    speaker = Speaker(cfg, audio)
    voice.update(speaker=speaker, audio=audio)
    ready_voice.set()

    def remind(text: str):
        log("⏰", f"час нагадати: {text}")
        # посеред розмови не перебиваємо — чекаємо, поки Хомі договорить і дослухає (до 40 с)
        for _ in range(80):
            if ui.state in ("sleep", "game", "paused"):
                break
            time.sleep(0.5)
        prev = ui.state
        try:
            audio.beep(up=True)
            audio.beep(up=True)              # подвійний сигнал — щоб нагадування не злилося з розмовою
            speak(speaker, audio, text)
            log("⏰", "сказала вголос")
        except Exception as e:
            log("помилка нагадування", str(e))
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
    # Детектор упевнений (схожість ≥ sure) — прокидаємось без перевірки Whisper: на ~1 с швидше.
    sure = max(detector.threshold, float(w.get("sure_score", 0.9))) if detector else 1.0
    end_ms = int(w.get("end_silence_ms", 350))   # скільки тиші після «Хооміі» = кінець слова
    speaker.warm(["Так?"])                       # «Так?» синтезуємо наперед — звучить миттєво
    log("👂", "Персональний детектор «Хооміі» увімкнено" if detector else
        "Персонального детектора ще немає — навчи: python -m agent.record_wake")

    log("Хомі", "Готова! Поклич мене: «Хооміі». Вийти — Ctrl+C або правий клік по кульці.")
    if cfg.get("ui", {}).get("greet", True):
        speak(speaker, audio, greeting(cfg["user"].get("name_vocative", cfg["user"]["name"]), time.localtime().tm_hour, random.randrange(10)))
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
        seg = audio.listen(end_silence_ms=end_ms, max_seconds=8,
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
        t0 = time.time()
        long_phrase = len(pcm) > 1.6 * 16000          # «Хомі, яка погода?» — звертання на початку
        if detector:
            score = detector.score(features.vector(pcm))
            if long_phrase:
                score = max(score, detector.score(features.vector(pcm, align="start")))
            if score < detector.threshold * 0.6:      # зовсім не схоже на твоє «Хооміі» — далі не дивимось
                continue
            if score >= sure:
                # детектор упевнений — не чекаємо на Whisper, прокидаємось одразу
                heard, woke = "", True
            else:
                heard = stt.wake(pcm)
                # обидві перевірки: звучить як твоє «Хооміі» І текст схожий на «Хомі»
                # або: майже дотягує до порогу, але Whisper чітко чує протяжне «Хомі» — теж ти
                woke = ((score >= detector.threshold and
                         (is_wake(heard, speech_s, 0.0, max_words) or split_wake(heard) is not None))
                        or (score >= detector.threshold * 0.8 and is_wake(heard, speech_s, min_s, max_words)))
            log("почула" if woke else "не те",
                f"«{heard or 'Хооміі'}» ({speech_s:.1f} с, схожість {score:.2f}, вирішила за {time.time() - t0:.2f} с)")
        else:
            heard = stt.wake(pcm)
            woke = is_wake(heard, speech_s, min_s, max_words)
            if woke:
                log("почула", f"«{heard}» ({speech_s:.1f} с, вирішила за {time.time() - t0:.2f} с)")
            elif "м" in collapse(heard):
                log("не те", f"«{heard}» ({speech_s:.1f} с)")   # підказка для налаштування min_seconds
        if woke:
            first = None
            if long_phrase and cfg["wake"].get("one_breath", True):
                # «Хомі, яка завтра погода?» — питання вже сказане, не перепитуємо «Так?»
                rest = split_wake(stt.command(pcm))
                if rest and len(rest.split()) >= 2:
                    first = (pcm, rest)
                    log("⚡", f"одним подихом: «{rest}»")
            conversation(cfg, audio, stt, brain, speaker, first)


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
    if sys.stdout is None or sys.stderr is None:      # запуск без вікна (pythonw): усе — у журнал
        stream = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
        globals()["_HEADLESS"] = True
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not single_instance():
        log("!", "Хомі вже запущена (дивись сферу в кутку екрана). Цю копію закриваю.")
        time.sleep(3)
        return
    cfg = load_config()
    CFG.update(cfg)
    try:                                 # версія коду — щоб з журналу було видно, чи Хомі оновилась
        import subprocess
        ver = subprocess.run(["git", "-C", str(AGENT_DIR.parent), "log", "-1", "--format=%h %cd", "--date=format:%d.%m %H:%M"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000 if sys.platform == "win32" else 0).stdout.strip()
        log("ℹ", f"версія Хомі: {ver}")
    except Exception:
        pass
    wake_click = threading.Event()

    if not cfg.get("ui", {}).get("widget", True):
        voice_loop(cfg, wake_click)
        return

    try:
        from .orb import OrbClient
        orb = OrbClient(position=cfg.get("ui", {}).get("position", "bottom-right"),
                        style=cfg.get("ui", {}).get("orb_style", "thinking"),
                        tint=bool(cfg.get("ui", {}).get("orb_tint", False)))
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
        elif event == "newtopic":
            if BRAIN:
                BRAIN[0].history = []
            log("🧹", "Нова тема — попередню розмову забула (пам'ять про тебе лишається).")
        elif event == "journal":
            os.startfile(LOG_FILE) if sys.platform == "win32" else None
        elif event == "quit" or not orb.alive():
            log("Хомі", "Вимикаюсь. Бувай!")
            os._exit(0)


if __name__ == "__main__":
    main()
