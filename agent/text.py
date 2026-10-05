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
        if out and (len(out[-1]) < 25 or len(out[-1]) + len(p) < 60):
            out[-1] += " " + p          # короткі речення склеюємо з наступним
        else:
            out.append(p)
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
