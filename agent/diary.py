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
Якщо розмова порожня (лише привітання чи команди на кшталт «пауза», «відкрий»), відповідай рівно: NONE

Розмова:
{dialog}

Підсумок:"""


class Diary:
    def __init__(self, path: Path = DIARY_FILE):
        self.path = path

    def _items(self) -> list[dict]:
        try:
            return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            return []

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

    def search(self, query: str, limit: int = 5) -> list[str]:
        words = {w for w in re.findall(r"[\w']+", query.lower()) if len(w) > 2}
        scored = []
        for it in self._items():
            text = it["s"].lower()
            score = sum(1 for w in words if w[:5] in text)      # грубо, але без зайвих моделей: «тренув…»
            if score:
                scored.append((score, it["t"], it))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [f"{self._date(it['t'])}: {it['s']}" for _, _, it in scored[:limit]]


def dialog_text(history: list[dict]) -> str:
    lines = []
    for m in history:
        if m.get("role") == "user":
            lines.append(f"Ігор: {m.get('content', '')}")
        elif m.get("role") == "assistant" and m.get("content"):
            lines.append(f"Хомі: {m['content']}")
    return "\n".join(lines)[-4000:]
