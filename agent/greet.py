"""Привітання після запуску. Різноманітність дає КОД, а не прохання до моделі «не повторюйся».

Раніше Gemma отримувала список попередніх привітань із проханням їх не повторювати, але цей список сам був
зразком для наслідування, а в підказці щоразу стояли ті самі щоденник («трекер») і пам'ять («ігри»). Заміри на 12
привітаннях підряд: усі починалися «Привіт, Ігорю!», 83% були про ігри, 100% закінчувалися питанням, два —
дослівно однакові. Тепер щоразу код обирає: один «кут» (мить / факт із пам'яті / остання розмова / що заплановано /
давно не бачились / жарт / цікавість / коротко), довжину, питання чи ні, емодзі чи ні, початок, ім'я чи без;
дає моделі лише цей «кут» (без списку старих привітань), а готовий текст перевіряє: схожість на недавні,
заборонені звороти, вигадані дії. Не пройшло — інший «кут». Усе не вийшло — запасне привітання з готових.
Перевірка: python -m agent.eval_dialogs --greet 12.
"""
import json
import random
import re
import time
from datetime import datetime
from difflib import SequenceMatcher

import requests

from .config import ollama_options
from .text import WEEKDAYS, claims_action, claims_work_in_progress, greeting, looks_ukrainian

KEEP = 12                       # скільки привітань пам'ятаємо
RECENT_FOR_SIMILARITY = 8       # з скількома останніми порівнюємо
MAX_SIMILARITY = 0.55
MAX_WORDS = 26

# Шаблонні звороти, у які модель сповзає щоразу
_BANNED = re.compile(r"я вже тут|в строю|у строю|готов\w+ до (?:справ|роботи|будь-чого|всього|твоїх)|нарешті я|"
                     r"в повній формі|в нормі|прийшла до тями|знову\s+(?:\w+\s+)?(?:в|у|до)\s+(?:ігор|ігри|гру|ігр)|"
                     r"знову\s+(?:граєш|гратимеш|грав|гри|загрався|загорнувся|зануришся)", re.IGNORECASE)
# Вигадки в привітанні: «бачу, ти в іграх» (вона не бачить), «ти просив…» (докір і переказ), «я вже працюю» (не працює),
# припущення про мій стан («мабуть, ти ще спиш»)
_PRESUME = re.compile(r"бачу,?\s+(?:що\s+)?ти|\bти\s+(?:просив|казав|дав|вирішив|занурився|зайнятий|занурений)\b|"
                      r"судячи з|\bти\s+(?:мабуть|напевно|певно)\b|\bя\s+(?:вже\s+|зараз\s+|тут\s+)?працюю\b|"
                      r"\bмабуть,?\s+ти\b|поки\s+ти\s+(?:ще\s+)?(?:мабуть|спиш|відпочива)|"
                      # докір, «знайомство» (ми давно знайомі) і вигадана подія («ти мене щойно перервав»)
                      r"\bти\s+знову\s+(?:за|в|у)\b|чого\s+це\s+ти|\bми\s+ж\s+(?:тільки|щойно)|"
                      r"знайомств|познайомит|\bти\s+мене\s+(?:щойно\s+)?(?:перерв|відволік)", re.IGNORECASE)
# Точний час у привітанні звучить кострубато («о 09:05», «двадцять три години шість хвилин»)
_CLOCK = re.compile(r"\d{1,2}[:.]\d{2}|годин\w*\s+(?:\w+\s+){1,2}хвилин|\bо\s+\w+\s+(?:годині|десятій|одинадцятій)\b",
                    re.IGNORECASE)
# Особисте не озвучуємо при кожному запуску (поруч можуть бути люди): родина, діти, здоров'я, гроші, адреси, дати
_SENSITIVE = re.compile(r"син\b|сина|синов|дочк|донь|дитин|дітей|діти|дружин|жін[кц]|чолов|мам[аиу]|тат[оа]|бать|"
                        r"брат|сестр|родин|вагітн|народи|день народження|\d{4}\s*р|здоров|лікар|хвор|діагноз|алерг|"
                        r"гроші|грошей|банк|картк|пароль|адрес|телефон|номер|зарплат|борг|кредит|ціль|вага|схуднут",
                        re.IGNORECASE)
# З пам'яті для привітання — лише легкі вподобання й заняття
_LIGHT_FACT = re.compile(r"люб|подоба|захоплю|граю|грає|слуха|дивит|цікав|вивча|прагн|хоче|тренуєт|готує|читає|"
                         r"смак|улюблен", re.IGNORECASE)
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")

STARTERS = ["Привіт", "Привіт, {name}", "О, {name}", "Ну що", "Слухай", "{name}", "Так", "Вітаю", "Я тут", "Хей",
            "О, привіт", "Знову я", "На зв'язку", "Ого", "Ну привіт", "Ех", "Хм"]

ANGLE_WEIGHTS = {"moment": 3.0, "memory": 2.0, "diary": 1.2, "plan": 5.0, "gap": 5.0, "wit": 2.0, "curious": 1.2,
                 "short": 3.0}


def part_of_day(now: datetime) -> str:
    h = now.hour
    return ("глибока ніч" if h < 5 else "рання година" if h < 8 else "ранок" if h < 12 else "день" if h < 17
            else "вечір" if h < 21 else "пізній вечір" if h < 24 else "ніч")


def load_history(path) -> list[dict]:
    """Історія привітань; старий формат (список рядків) теж читаємо."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"text": x} if isinstance(x, str) else x for x in raw if x]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def first_words(text: str, n: int = 3) -> str:
    return " ".join(re.findall(r"[\w']+", text.lower())[:n])


def too_similar(text: str, recent: list[str]) -> bool:
    if any(similarity(text, r) > MAX_SIMILARITY for r in recent[-RECENT_FOR_SIMILARITY:]):
        return True
    return first_words(text, 2) in {first_words(r, 2) for r in recent[-3:]}      # той самий початок підряд


def check(text: str, form: dict, recent: list[str]) -> str | None:
    """Чому привітання не підходить (None — підходить)."""
    if not text or not looks_ukrainian(text):
        return "не українською"
    if len(text.split()) > MAX_WORDS:
        return "задовге"
    if _BANNED.search(text):
        return "шаблонний зворот"
    if _PRESUME.search(text):
        return "припускає, що я роблю, або вигадує свою роботу"
    if _CLOCK.search(text):
        return "читає точний час"
    if _SENSITIVE.search(text):
        return "особисте (родина, здоров'я, гроші)"
    if "?" in text and len(text.split()) > 16:
        return "задовге питання"
    if "?" in text and not form["question"]:
        return "питання, хоча не треба"
    if claims_action(text) or claims_work_in_progress(text):
        return "каже, що щось робила"
    if too_similar(text, recent):
        return "схоже на недавні"
    return None


def gather(brain, now: datetime, history: list[dict]) -> dict:
    """Що в неї справді є для привітання (кожне — тільки коли воно правдиве)."""
    ctx: dict = {}
    used = " ".join(h.get("hook", "") for h in history[-3:])
    try:
        facts = [m for m in brain._memories()
                 if m and m not in used and _LIGHT_FACT.search(m) and not _SENSITIVE.search(m)]
    except Exception:  # noqa: BLE001
        facts = []
    if facts:
        ctx["memory"] = random.choice(facts)
    try:
        items = [it for it in brain.diary._items()
                 if time.time() - it["t"] < 3 * 86400 and it["s"] not in used and not _SENSITIVE.search(it["s"])][-4:]
    except Exception:  # noqa: BLE001
        items = []
    if items:
        ctx["diary"] = random.choice(items)["s"]
    try:
        plan = brain.tools.jobs.describe()
    except Exception:  # noqa: BLE001
        plan = ""
    if plan:
        ctx["plan"] = plan
    last = next((h["t"] for h in reversed(history) if h.get("t")), None)
    if last:
        gap_min = (now.timestamp() - last) / 60
        if gap_min < 30:
            ctx["gap"] = "ти щойно перезапустила мене — ми бачились кілька хвилин тому; скажи про це жартома, без пояснень"
        elif gap_min > 8 * 60:
            hours = int(gap_min // 60)
            ctx["gap"] = (f"ми не розмовляли вже {hours // 24} дн." if hours >= 48 else
                          f"ми не розмовляли близько {hours} год.") + " Скажи, що рада, що я повернувся"
    return ctx


def pick_angle(ctx: dict, history: list[dict], exclude: set[str]) -> str:
    recent_angles = {h.get("angle") for h in history[-2:]}
    weights = {a: w for a, w in ANGLE_WEIGHTS.items()
               if a not in exclude and (a in ctx or a in ("moment", "wit", "curious", "short"))}
    fresh = {a: w for a, w in weights.items() if a not in recent_angles}
    pool = fresh or weights or {"moment": 1.0}
    return random.choices(list(pool), weights=list(pool.values()))[0]


def build_form(angle: str, history: list[dict], name: str) -> dict:
    """Форма привітання: довжина, питання, емодзі, початок, ім'я — випадково, але не так, як щойно."""
    used_starters = {h.get("starter") for h in history[-4:]}
    starters = [s for s in STARTERS if s not in used_starters] or STARTERS
    starter = random.choice(starters) if random.random() < 0.7 else ""
    length = ("дуже коротко: 2–6 слів" if angle == "short" else
              random.choices(["одне коротке речення", "одне речення", "два коротких речення"], weights=[3, 4, 3])[0])
    question = angle == "curious" or random.random() < 0.15
    return {"starter": starter, "length": length, "question": question,
            "emoji": random.random() < 0.12, "name": random.random() < 0.5}


def angle_instruction(angle: str, ctx: dict, now: datetime) -> str:
    when = f"{part_of_day(now)}, {WEEKDAYS[now.weekday()]}"          # без точного часу: «о 09:05» звучить кострубато
    return {
        "moment": f"тепло згадай саме цю мить ({when}) — одним штрихом, без точного часу й без припущень про те, чим я "
                  "зараз зайнятий",
        "memory": f"мимохідь, тепло скажи, що пам'ятаєш про мене: «{ctx.get('memory', '')}» — як щось, що ти знаєш про "
                  "мене загалом, а не про те, чим я зараз займаюсь; не питай про це",
        "diary": f"спитай тепло, одним коротким реченням, як справи з темою нашої останньої розмови "
                 f"(«{ctx.get('diary', '')}»); не переказуй її, не докоряй і нічого не обіцяй",
        "plan": f"скажи про те, що в мене заплановано: {ctx.get('plan', '')}",
        "gap": ctx.get("gap", ""),
        "wit": f"зроби легке дружнє спостереження чи жарт про цю пору ({when}), без точного часу; не припускай, чим я "
               "зайнятий, і не про ігри",
        "curious": "спитай мене про щось нове про мене, чого ти ще не знаєш (смаки, звички, плани) — одне коротке "
                   "питання, до 10 слів; не про ігри",
        "short": "лише коротко й по-дружньому дай знати, що ти поруч",
    }[angle]


def build_prompt(angle: str, ctx: dict, form: dict, now: datetime, name: str) -> str:
    rules = [f"форма: {form['length']}",
             "заверши питанням" if form["question"] else "без питання",
             "додай один доречний емодзі" if form["emoji"] else "без емодзі",
             f"звернись до мене на ім'я «{name}»" if form["name"] else "без імені",
             f"почни зі слів «{form['starter'].format(name=name)}»" if form["starter"] else
             "не починай словами «Привіт, " + name + "»"]
    return (f"(Службове: тебе щойно запустили, ти завантажилась. Привітайся зі мною так: "
            f"{angle_instruction(angle, ctx, now)}. {'; '.join(rules)}. "
            "Не вживай звороти «Я вже тут», «в строю», «готова до справ», «нарешті я», «знову в ігри». Не кажи, що ти бачиш "
            "чи знаєш, чим я зараз займаюсь; не припускай («мабуть, ти…»); не докоряй; не переказуй мої минулі "
            "прохання; не кажи, що ти щось робила чи працюєш. Будь теплою й невимушеною, як подруга. Виведи лише саме "
            "привітання, як воно прозвучить голосом.)")


def ask_model(brain, prompt: str) -> str:
    o = brain.cfg["ollama"]
    r = requests.post(f"{o['url']}/api/chat", timeout=90, json={
        "model": o["model"], "stream": False, "think": False, "keep_alive": o.get("keep_alive", "24h"),
        "options": ollama_options(brain.cfg, temperature=0.9, num_predict=70),
        # лише характер: щоденник, пам'ять і розмовні кейси в підказці щоразу тягнули її до «трекера» й «ігор»
        "messages": [{"role": "system", "content": brain._system_prompt(light=True)},
                     {"role": "user", "content": prompt}]})
    r.raise_for_status()
    return (r.json()["message"].get("content") or "").strip()


_JUDGE = ("Ти — суворий коректор української мови. Тобі дають одне речення, яке сказав голосовий помічник. "
          "Відповідай ОДНИМ словом. НІ — якщо в реченні є неіснуюче слово, слово вжите не за змістом, "
          "незграбний чи безглуздий зворот, або воно так по-українськи не кажуть. ТАК — якщо речення звучить "
          "природно, граматично правильно і має сенс.")


def sounds_natural(brain, text: str) -> bool:
    """Чи звучить привітання по-українськи. Мала модель інколи вигадує слова або вживає справжні не за змістом
    («встигла з тобою розмитися»). Словник (pymorphy) такого не ловить — «розмитися» в ньому є, — а сама модель
    як суддя при температурі 0 упіймала 8 з 8 таких речень (хибна тривога ~16% — тоді просто нова спроба).
    Суддя недоступний — привітання не блокуємо."""
    o = brain.cfg["ollama"]
    try:
        r = requests.post(f"{o['url']}/api/chat", timeout=30, json={
            "model": o["model"], "stream": False, "think": False, "keep_alive": o.get("keep_alive", "24h"),
            "options": ollama_options(brain.cfg, temperature=0.0, num_predict=4),
            "messages": [{"role": "system", "content": _JUDGE}, {"role": "user", "content": text}]})
        r.raise_for_status()
        answer = (r.json()["message"].get("content") or "").strip()
    except (requests.RequestException, ValueError, KeyError):
        return True
    return not answer.upper().startswith("НІ")


def make_greeting(brain, now: datetime | None = None, attempts: int = 3) -> str | None:
    now = now or datetime.now()
    name = brain.cfg["user"].get("name_vocative", brain.cfg["user"]["name"])
    history = load_history(brain.GREET_FILE)
    recent = [h["text"] for h in history]
    ctx = gather(brain, now, history)
    tried: set[str] = set()
    text, angle, form, tries = None, "", {}, 0
    for tries in range(1, attempts + 1):
        angle = pick_angle(ctx, history, tried)
        tried.add(angle)
        form = build_form(angle, history, name)
        try:
            text = brain.polish("", ask_model(brain, build_prompt(angle, ctx, form, now, name)))
        except (requests.RequestException, ValueError, KeyError):
            return None
        if not form["emoji"]:
            text = _EMOJI.sub("", text).strip()
        text = text.strip(" \"«»")
        if check(text, form, recent) is None and sounds_natural(brain, text):
            break
        text = None
    if text is None:                  # жодна спроба не пройшла перевірку — запасне з готових, яке не повторює недавні
        pool = [greeting(name, now.hour, i) for i in range(6)]
        text = next((g for g in pool if not too_similar(g, recent)), pool[0])
        angle, form = "static", {"starter": ""}
    history.append({"t": now.timestamp(), "text": text, "angle": angle, "tries": tries,
                    "starter": form.get("starter", ""), "hook": ctx.get(angle, "") if isinstance(ctx.get(angle), str) else ""})
    try:
        brain.GREET_FILE.write_text(json.dumps(history[-KEEP:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return text
