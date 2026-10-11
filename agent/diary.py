"""Щоденник розмов: Хомі пам'ятає, про що ви говорили, а не лише окремі факти.

Після кожної розмови Gemma одним коротким запитом підсумовує її (1–3 речення) → agent\\diary.jsonl.
Останні кілька підсумків Хомі бачить завжди («ОСТАННІ НАШІ РОЗМОВИ»), старіші знаходить інструментом
recall («про що ми говорили минулого тижня про тренування?»). Легко: один запит після розмови.
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

DIARY_FILE = Path(__file__).resolve().parent / "diary.jsonl"

SUMMARY_PROMPT = """Ось розмова голосової помічниці Хомі з її господарем Ігорем.
Коротко підсумуй її українською (1–3 речення, від третьої особи): про що говорили, що вирішили,
що Ігор просив зробити чи запам'ятати, що для нього важливо. Без води й без вступів.
ПРАВИЛА — щоденник має бути правдивим:
- Що Хомі ЗРОБИЛА, бери лише з позначок [зроблено: …]. Її слова «почала писати», «працюю над», «зараз
  зроблю» без такої позначки — не факт: не пиши, що вона це зробила чи робить.
- Фрази Ігоря, схожі на помилку розпізнавання мови (безглузді слова, незнайомі «імена» без пояснення,
  обірвані речення), пропускай — не вигадуй, що він мав на увазі.
- Нічого не додавай від себе.
Якщо розмова порожня (лише привітання, шум чи команди на кшталт «пауза», «відкрий»), відповідай рівно: NONE

Розмова:
{dialog}

Підсумок:"""

# «Хомі почала писати сторінку», «Хомі зафіксувала інформацію» — у щоденнику лише якщо в розмові щось справді зроблено
_HOMI_DID = re.compile(r"\bХомі\b[^.!?]*?\b(?:створила|відкрила|запустила|поставила|записала|зробила|розпочала|"
                       r"почала|написала|нагадала|закрила|зафіксувала|запам'ятала|працює|працювала|пише|писала|"
                       r"прийняла завдання|взялася|взяла на себе|продовжує|продовжила)\b", re.IGNORECASE)
_FALLBACK = ("Не зрозуміла", "Ой, я не можу достукатися")


class Diary:
    def __init__(self, path: Path = DIARY_FILE):
        self.path = path

    def _items(self) -> list[dict]:
        try:
            return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            return []

    def forget_last(self) -> str | None:
        """«Забудь останню розмову» — прибрати останній запис (наприклад, із помилок розпізнавання)."""
        items = self._items()
        if not items:
            return None
        last = items.pop()
        self.path.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
        return last["s"]

    def add(self, summary: str, when: float | None = None):
        summary = " ".join(summary.split())
        if not summary or summary.upper().startswith("NONE"):
            return
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": when or time.time(), "s": summary}, ensure_ascii=False) + "\n")

    @staticmethod
    def _date(t: float) -> str:
        return datetime.fromtimestamp(t).strftime("%d.%m %H:%M")

    def prompt_block(self, n: int = 3) -> str:
        items = self._items()[-n:]
        if not items:
            return ""
        return ("\nОСТАННІ НАШІ РОЗМОВИ (щоденник; згадуй доречно, не переказуй без потреби)\n"
                + "\n".join(f"- {self._date(it['t'])}: {it['s']}" for it in items) + "\n")

    @staticmethod
    def _period(query: str) -> tuple[float, float] | None:
        """«вчора», «сьогодні», «на тижні» → проміжок часу (раніше «вчора» шукалось як слово й нічого не знаходило)."""
        q, now = query.lower(), datetime.now()
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for word, start, end in (("позавчора", day0 - 2 * 86400, day0 - 86400), ("вчора", day0 - 86400, day0),
                                 ("сьогодні", day0, day0 + 86400), ("тижн", day0 - 7 * 86400, day0 + 86400)):
            if word in q:
                return start, end
        return None

    _NOT_TOPIC = {"про", "що", "ми", "тобою", "пам'ятаєш", "говорили", "обговорювали", "розмовляли", "вирішили",
                  "вчора", "сьогодні", "позавчора", "минулого", "разу", "тижня", "тижні", "тиждень", "раніше",
                  "недавно", "останній", "останнього", "згадай", "нагадай", "розкажи"}

    def search(self, query: str, limit: int = 5) -> list[str]:
        items = self._items()
        period = self._period(query)
        if period:
            items = [it for it in items if period[0] <= it["t"] < period[1]]
        words = {w for w in re.findall(r"[\w']+", query.lower()) if len(w) > 2 and w not in self._NOT_TOPIC}
        if not words:          # «про що ми говорили вчора / минулого разу» — без теми: просто останні розмови
            chosen = items[-limit if period else -3:]
            return [f"{self._date(it['t'])}: {it['s']}" for it in reversed(chosen)]
        scored = []
        for it in items:
            text = it["s"].lower()
            # грубо, але без зайвих моделей: основа слова («трену…»); у коротких — ще коротша, бо «Львів» → «Львова»
            score = sum(1 for w in words if w[:max(3, min(5, len(w) - 2))] in text)
            if score:
                scored.append((score, it["t"], it))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [f"{self._date(it['t'])}: {it['s']}" for _, _, it in scored[:limit]]


def dialog_text(history: list[dict]) -> str:
    """Розмова для підсумку — з позначками, що справді зробив код (квитанції), а що лише сказано."""
    lines = []
    for m in history:
        if m.get("role") == "user":
            lines.append(f"Ігор: {m.get('content', '')}")
        elif m.get("role") == "assistant" and m.get("content"):
            done = m.get("done") or []
            mark = f" [зроблено: {'; '.join(done)}]" if done else " [жодної дії не виконано]"
            lines.append(f"Хомі: {m['content']}{mark}")
    return "\n".join(lines)[-4000:]


def meaningful_turns(history: list[dict]) -> int:
    """Скільки реплік Ігоря справді щось означали: без шуму, чужої мови й тих, на які Хомі відповіла
    «Не зрозуміла…» — з такої «розмови» щоденник записував сміття («Вересно стосовно Стеринка»)."""
    from .text import is_noise, looks_ukrainian
    count = 0
    for i, m in enumerate(history):
        if m.get("role") != "user":
            continue
        text = str(m.get("content", "")).strip()
        reply = next((str(x.get("content", "")) for x in history[i + 1:i + 2] if x.get("role") == "assistant"), "")
        if text and looks_ukrainian(text) and not is_noise(text) and not reply.startswith(_FALLBACK):
            count += 1
    return count


def drop_unproven(summary: str, history: list[dict]) -> str:
    """Якщо в розмові код не виконав жодної дії — речення «Хомі почала / зробила / пише…» з підсумку прибираємо."""
    if any(m.get("done") for m in history if m.get("role") == "assistant"):
        return summary
    keep = [s for s in re.split(r"(?<=[.!?…])\s+", summary.strip()) if s and not _HOMI_DID.search(s)]
    return " ".join(keep).strip()
