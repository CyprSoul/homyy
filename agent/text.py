"""Чисті текстові функції: без звуку й мережі, щоб їх легко тестувати."""
import re
from datetime import date

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
WEEKDAYS = ["понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя"]

_WAKE_PATTERNS = [
    re.compile(r"хо[уоа]?м[іиїйеє]"),   # хомі, хоумі, хомій…
    re.compile(r"ho[uo]?m[iey]"),        # homi, homie, houmy…
]


def ukr_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year} року"


def collapse(text: str) -> str:
    """Нижній регістр, лише літери, повтори літер стиснуті: «Хоооуммміііі!» → «хоумі»."""
    letters = re.sub(r"[^a-zа-яіїєґ' ]", " ", text.lower().replace("’", "'"))
    return re.sub(r"(.)\1+", r"\1", re.sub(r"\s+", " ", letters)).strip()


def is_wake(transcript: str, duration_s: float, min_seconds: float, max_words: int) -> bool:
    """Протяжне «Хоооуммміііі»: коротка фраза, довга за часом, схожа на «хомі»."""
    words = collapse(transcript).split()
    if not words or len(words) > max_words or duration_s < min_seconds:
        return False
    return any(p.search(w) for w in words for p in _WAKE_PATTERNS)


def extract_prompt(markdown: str) -> str:
    """Перший блок ``` … ``` з файлу характеру."""
    m = re.search(r"```\n(.*?)\n```", markdown, re.S)
    if not m:
        raise ValueError("У файлі характеру немає блоку ``` з промтом")
    return m.group(1)


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def clean_for_speech(text: str) -> str:
    """Прибирає те, що не варто читати вголос: емодзі, markdown, посилання."""
    text = re.sub(r"<think>.*?</think>", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = _EMOJI.sub("", text)
    text = re.sub(r"[*_#`>|]+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str, max_len: int = 220) -> list[str]:
    """Ділить на речення, щоб перше речення озвучувалось, поки готуються наступні."""
    parts = re.split(r"(?<=[.!?…])\s+", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # короткі речення склеюємо з наступним — але не перше: чим воно коротше, тим швидше Хомі заговорить
        if out and (len(out) > 1 or len(out[0]) < 12) and (len(out[-1]) < 25 or len(out[-1]) + len(p) < 60):
            out[-1] += " " + p
        else:
            out.append(p)
    if out and len(out[0]) > 70:        # довге перше речення ділимо по комі
        m = re.search(r",\s+", out[0][20:])
        if m:
            cut = 20 + m.end()
            out[0:1] = [out[0][:cut].rstrip(), out[0][cut:]]
    return [s[:max_len] for s in out]


def date_diff(start: date, end: date) -> dict:
    """Точна різниця дат у роках, місяцях і днях (моделі погано рахують дати)."""
    sign = 1
    if end < start:
        start, end, sign = end, start, -1
    years = end.year - start.year
    months = end.month - start.month
    days = end.day - start.day
    if days < 0:
        months -= 1
        prev_month = (end.month - 2) % 12 + 1
        prev_year = end.year if end.month > 1 else end.year - 1
        days += _days_in_month(prev_year, prev_month)
    if months < 0:
        years -= 1
        months += 12
    return {"years": years, "months": months, "days": days,
            "total_days": (end - start).days, "direction": "майбутнє" if sign < 0 else "минуле"}


def _days_in_month(y: int, m: int) -> int:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return (nxt - date(y, m, 1)).days


# Фрази, які Whisper «чує» в тиші чи шумі (навчився на субтитрах відео).
_HALLUCINATIONS = {
    "дякую за перегляд", "дякуємо за перегляд", "субтитри", "субтитри зроблено",
    "підписуйтесь на канал", "продовження слідує", "дякую", "thank you", "you",
}
_STOP_WORDS = {"все", "всьо", "стоп", "бувай", "відбій", "достатньо", "вистачить"}


def is_noise(transcript: str) -> bool:
    t = collapse(transcript).strip(" '")
    return not t or t in _HALLUCINATIONS or len(t) < 2


def is_stop(transcript: str) -> bool:
    """«Дякую, це все», «Все, бувай», «Стоп» — коротка фраза з «стоп-словом»."""
    words = collapse(transcript).replace("'", "").split()
    return 0 < len(words) <= 4 and any(w in _STOP_WORDS for w in words)


_GREETINGS = {
    "morning": ["Доброго ранку, {name}! Я тут.", "Ранок добрий, {name}! Хомі на зв'язку."],
    "day":     ["Привіт, {name}! Я тут, клич, якщо що.", "Я на місці, {name}. Слухаю, коли покличеш."],
    "evening": ["Добрий вечір, {name}! Я поруч.", "Вечір добрий, {name}! Хомі на зв'язку."],
    "night":   ["Не спиться, {name}? Я тут.", "Я тут, {name}. Тихенько слухаю."],
}


def greeting(name: str, hour: int, pick: int = 0) -> str:
    part = ("night" if hour < 5 else "morning" if hour < 12 else
            "day" if hour < 18 else "evening" if hour < 23 else "night")
    options = _GREETINGS[part]
    return options[pick % len(options)].format(name=name)


def is_pause(transcript: str) -> bool:
    """«Не слухай», «не підслуховуй» — пауза до кліку чи «Продовжити» в меню сфери."""
    t = collapse(transcript).replace("'", "")
    return "не слухай" in t or "не підслуховуй" in t


_YES = {"так", "ага", "угу", "давай", "звісно", "звичайно", "підтверджую", "можна", "впевнений", "точно", "yes"}


def is_yes(transcript: str) -> bool:
    """Коротка згода: «так», «так, давай», «ага». Заперечення («ні», «не треба») — ні."""
    words = collapse(transcript).replace("'", "").split()
    if not words or len(words) > 5 or any(w in ("ні", "не", "стоп", "скасуй") for w in words):
        return False
    return any(w in _YES for w in words)


_NEW_TOPIC = ("нова тема", "нову тему", "змінимо тему", "змінімо тему", "почнемо спочатку", "забудь розмову",
              "забудь про це", "інша тема")


def is_new_topic(transcript: str) -> bool:
    """«Нова тема», «змінимо тему», «почнемо спочатку» — забути поточну розмову (не пам'ять)."""
    t = collapse(transcript).replace("'", "")
    return len(t.split()) <= 6 and any(p.replace("'", "") in t for p in _NEW_TOPIC)


_RU_ONLY = set("ыэъё")
# Часті російські слова без «ы/э/ъ/ё» — Parakeet інколи пише «Привет» замість «Привіт»
_RU_WORDS = {"привет", "что", "это", "как", "где", "когда", "хорошо", "спасибо", "пожалуйста", "сегодня",
             "сейчас", "тебя", "меня", "есть", "нет", "да", "очень", "только", "можно", "нужно", "почему",
             "здравствуй", "здравствуйте", "пока", "тоже", "теперь", "давно", "кто", "или", "она", "они",
             "расскажи", "рассказать", "скажите", "сколько", "сделай", "включи", "выключи", "открой",
             "найди", "какая", "какой", "какие", "какое", "зачем", "мне", "его", "еще", "время",
             "будет", "этот", "эта", "можешь", "который", "которая",
             "посмотри", "напомни", "подожди", "ладно", "конечно", "сделать"}


def looks_ukrainian(transcript: str) -> bool:
    """Чи схоже розпізнане на українську: без суто російських букв і не латиницею.

    Parakeet сам вгадує мову й на живому мікрофоні інколи пише російською чи англійською
    («Ты тут…», «Uh none of mine») — тоді перерозпізнаємо Whisper'ом з мовою «uk».
    """
    letters = [c for c in transcript.lower() if c.isalpha()]
    if not letters:
        return True
    if any(c in _RU_ONLY for c in letters):
        return False
    words = set(re.findall(r"[а-яіїєґ']+", transcript.lower()))
    if words & _RU_WORDS or any(w.startswith("расс") for w in words):
        return False
    latin = sum("a" <= c <= "z" for c in letters)
    return latin / len(letters) < 0.5


_CONNECTORS = {"і", "й", "та", "а", "але", "що", "щоб", "бо", "тому", "або", "чи", "як", "коли", "якщо",
               "в", "у", "на", "з", "із", "до", "про", "для", "від", "ну", "ем", "е", "ее", "це", "мені",
               "мій", "моя", "моє", "мої", "ти", "я", "він", "вона", "ми", "ви", "вони", "дуже", "ще",
               "м", "ем", "ам", "хм"}       # «Я хочу м…» — людина підбирає слово


# Дієслова, після яких зазвичай іде продовження: «Я хочу…», «Нагадай…», «Розкажи…»
_DANGLING = {"хочу", "хочеш", "можеш", "можна", "треба", "потрібно", "розкажи", "скажи", "нагадай",
             "знайди", "відкрий", "увімкни", "вімкни", "постав", "покажи", "давай", "думаю", "знаєш",
             "слухай", "подивись", "порадь", "поясни", "переклади", "запиши", "запам'ятай", "запамятай"}


def unfinished(transcript: str) -> float:
    """Скільки ще почекати (с), бо фраза звучить незакінченою; 0 — договорив.

    «Я займаюся тим, що…», «а ще», «Розкажи про» — людина просто набирає повітря.
    """
    t = transcript.strip()
    if not t:
        return 0.0
    words = collapse(t).replace("'", "").split()
    if t[-1] in ",:;—-…" or t.endswith("..") or (words and words[-1] in _CONNECTORS | _DANGLING):
        return 2.5
    if t[-1] not in ".?!":
        return 0.6
    if len(words) <= 2 and t[-1] != "?":     # «Я хочу.» — розпізнавач ставить крапку, хоч ти лише вдихнув
        return 0.7
    return 0.0


_INTERRUPT_WORDS = {"стоп", "стій", "стоять", "зупинись", "зупинися", "досить", "почекай", "чекай",
                    "тихо", "замовкни", "перестань", "хомі", "хома", "хоми", "стривай"}


def interrupt_request(heard: str, speaking: str) -> str | None:
    """Чи просить людина перебити Хомі, поки та говорить.

    Повертає те, що людина сказала після «стоп»-слова ("" — просто зупинитись), або None.
    Слова, які Хомі зараз сама вимовляє (її голос із колонок), не рахуються.
    """
    words = collapse(heard).replace("'", "").split()
    own = set(collapse(speaking).replace("'", "").split())
    for i, w in enumerate(words):
        if w in _INTERRUPT_WORDS and w not in own:
            rest = words[i + 1:]
            while rest and rest[0] in _INTERRUPT_WORDS:      # «стоп, стоп, Хомі, …»
                rest = rest[1:]
            return " ".join(rest) if len(rest) >= 2 else ""
    return None
