"""Уроки з розмов: Хомі вчиться на твоїх зауваженнях.

Сказав «ні, не так», «я мав на увазі…», «коротше», «навіщо ти…», вилаявся — Хомі (у фоні,
поки розмова йде далі) просить Gemma сформулювати ОДНЕ коротке правило: що робити інакше.
Правило записується в agent\\lessons.json і відтепер щоразу додається до її характеру
(«УРОКИ З НАШИХ РОЗМОВ»). Похвала («супер», «саме те») підсилює правило, яке вже спрацювало.

Можна вчити й напряму: «Хомі, запам'ятай правило: коли я кажу "ввімкни щось", вмикай рок».
Забути: «Хомі, забудь урок про рок».
"""
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

LESSONS_FILE = Path(__file__).resolve().parent / "lessons.json"
MAX_IN_PROMPT = 15

_NEG = re.compile(r"(^ні[,.! ]|не так|не те|не це|я мав на увазі|я ж казав|я казав|ти не зрозуміла|навіщо ти|"
                  r"не треба було|не роби так|не роби цього|задовбала|заїбала|дістала|тупиш|тупа|бляха|блять|"
                  r"нафіга|навіщо це|коротше давай|без води|я не просив|я не про це|не слухаєш)", re.IGNORECASE)
_POS = re.compile(r"(^супер|саме те|молодець|ідеально|чудово|оце так|клас|круто|те що треба|красава)", re.IGNORECASE)
_TEACH = re.compile(r"^(?:хомі,?\s*)?запам'?ятай (?:правило|урок|собі правило)[:,]?\s*(.+)$", re.IGNORECASE)
_FORGET = re.compile(r"^(?:хомі,?\s*)?забудь (?:урок|правило) (?:про )?(.+)$", re.IGNORECASE)


def feedback(text: str) -> str | None:
    """«neg» — зауваження/невдоволення, «pos» — похвала, None — звичайна фраза."""
    t = text.strip().lower().replace("’", "'")
    if _NEG.search(t):
        return "neg"
    if _POS.search(t) and len(t.split()) <= 6:
        return "pos"
    return None


def taught_rule(text: str) -> str | None:
    m = _TEACH.match(text.strip().replace("’", "'"))
    return m.group(1).strip().rstrip(".") + "." if m else None


def forget_request(text: str) -> str | None:
    m = _FORGET.match(text.strip())
    return m.group(1).strip() if m else None


class LessonBook:
    def __init__(self, path: Path = LESSONS_FILE):
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

    def add(self, rule: str, source: str = "") -> bool:
        """Додати правило (або підсилити схоже). True — нове."""
        rule = " ".join(rule.split())
        if not rule or len(rule) < 8:
            return False
        for it in self.items:
            if SequenceMatcher(None, it["rule"].lower(), rule.lower()).ratio() > 0.75:
                it["weight"] += 1
                it["last"] = time.time()
                self._save()
                return False
        self.items.append({"rule": rule, "weight": 1, "source": source[:200], "last": time.time()})
        self.items = self.items[-200:]
        self._save()
        return True

    def reinforce_last(self):
        if self.items:
            newest = max(self.items, key=lambda it: it["last"])
            newest["weight"] += 1
            self._save()

    def forget(self, about: str) -> int:
        about = about.lower()
        before = len(self.items)
        self.items = [it for it in self.items
                      if about not in it["rule"].lower()
                      and SequenceMatcher(None, about, it["rule"].lower()).ratio() < 0.5]
        self._save()
        return before - len(self.items)

    def prompt_block(self) -> str:
        if not self.items:
            return ""
        top = sorted(self.items, key=lambda it: (it["weight"], it["last"]), reverse=True)[:MAX_IN_PROMPT]
        return ("\nУРОКИ З НАШИХ РОЗМОВ (ти вже вчилася на цьому — дотримуйся)\n"
                + "\n".join(f"- {it['rule']}" for it in top) + "\n")


LESSON_PROMPT = """Ти аналізуєш розмову голосової помічниці Хомі з її господарем.
Господар висловив невдоволення. Сформулюй ОДНЕ коротке правило для Хомі (одне речення, українською,
наказовий спосіб, звертання на «ти»), щоб наступного разу вона зробила так, як він хоче.
Правило має бути загальним (не про один конкретний випадок), але конкретним щодо поведінки.
Якщо з розмови незрозуміло, що саме не так, — відповідай рівно словом NONE.

Його прохання: {request}
Відповідь Хомі: {answer}
Його реакція: {feedback}

Правило:"""
