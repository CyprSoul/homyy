"""Навички, яких Хомі вчиться сама: що ти просиш кілька разів — вона запам'ятовує, як це зробила,
і наступного разу робить одразу, без «роздумів» Gemma.

Як це працює: Gemma виконала прохання інструментами (відкрила програму, натиснула кнопку…) → Хомі
записує «фраза → що зробила». Коли та сама дія вдалась удруге на схоже прохання — це навичка.
Далі на таку фразу вона одразу повторює ці кроки (≈0.5 с замість 3–8 с).

Навички — у agent\\skills.json (можна подивитися й поправити руками). Небезпечні дії
(вимкнення, закриття програм, видалення…) навичками не стають — вони завжди з перепитуванням.
"""
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from .text import collapse, split_wake

SKILLS_FILE = Path(__file__).resolve().parent / "skills.json"
LEARNABLE = {"open_app", "open_website", "play_music", "media", "window", "click_on_screen", "search_on_site"}
TIMES_TO_LEARN = 2
SIMILAR = 0.85
_FILLER = {"будь", "ласка", "ну", "а", "давай", "мені", "можеш", "будьласка"}
_FAIL = ("Помилка", "Не ", "Невідом", "ПОТРІБНЕ", "Такої", "Можна відкривати лише", "Зараз нічого не грає")


def key(text: str) -> str:
    rest = split_wake(text)
    words = collapse(rest if rest else text).replace("'", "").split()
    return " ".join(w for w in words if w not in _FILLER)


def _calls_key(calls) -> str:
    return json.dumps(calls, ensure_ascii=False, sort_keys=True)


class SkillBook:
    def __init__(self, path: Path = SKILLS_FILE):
        self.path = path
        try:
            self.items: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _similar(a: str, b: str) -> float:
        return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()

    def match(self, text: str) -> dict | None:
        """Вивчена навичка для цієї фрази (або None)."""
        k = key(text)
        if not k:
            return None
        best = max(((self._similar(k, it["key"]), it) for it in self.items if it.get("learned")),
                   default=(0, None), key=lambda x: x[0])
        return best[1] if best[0] >= SIMILAR else None

    def observe(self, text: str, calls: list[dict], results: list[str]) -> bool:
        """Запам'ятати, що Gemma зробила на це прохання. True — щойно стало навичкою."""
        k = key(text)
        if not k or not calls:
            return False
        if any(c["name"] not in LEARNABLE for c in calls):
            return False
        if any(str(r).startswith(_FAIL) for r in results):
            return False
        clean = [{"name": c["name"], "arguments": {a: v for a, v in (c.get("arguments") or {}).items()
                                                   if a != "confirmed"}} for c in calls]
        ck = _calls_key(clean)
        for it in self.items:
            if _calls_key(it["calls"]) == ck and self._similar(k, it["key"]) >= SIMILAR:
                it["count"] += 1
                it["last"] = time.time()
                newly = not it.get("learned") and it["count"] >= TIMES_TO_LEARN
                if newly:
                    it["learned"] = True
                self._save()
                return newly
        self.items.append({"key": k, "phrase": text, "calls": clean, "count": 1, "learned": False,
                           "last": time.time()})
        self.items = self.items[-300:]
        self._save()
        return False

    def forget(self, text: str) -> bool:
        k = key(re.sub(r"^(забудь|розучись)( як| навичку)?", "", text.strip(), flags=re.I))
        before = len(self.items)
        self.items = [it for it in self.items if self._similar(k, it["key"]) < SIMILAR]
        self._save()
        return len(self.items) != before

    def learned(self) -> list[dict]:
        return [it for it in self.items if it.get("learned")]
