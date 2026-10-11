"""Швидкі команди без Gemma: що зробити з фразою одразу (інструмент і аргументи) — чи віддати її Gemma.

Одна функція і для живої розмови (main.conversation), і для набору перевірок (agent.eval_dialogs),
щоб перевірки йшли тим самим шляхом, що й справжня розмова. Сама нічого не виконує.
"""
import re
import time
from dataclasses import dataclass, field

from .text import (click_intent, folder_intent, is_no, is_yes, media_intent, open_page_intent, page_retry_intent,
                   page_status_intent, wants_selection, window_intent)


@dataclass
class Route:
    kind: str                  # tool | confirm | decline | selection | skill | forget_skill
    tool: str = ""
    args: dict = field(default_factory=dict)
    skill: dict | None = None
    summarize: str = ""        # результат (вміст папки, щоденник) потім коротко переказує Gemma — з цією приміткою


_FORGET_SKILL = re.compile(r"^(?:хомі,?\s*)?(?:забудь|розучись),? як", re.I)
# «Про що ми вчора говорили?», «Що ми вирішили щодо тренувань?» — модель тут вигадувала спогади або «не розуміла»
_RECALL = re.compile(r"\bщо ми (?:з тобою )?(?:[\w']+\s+){0,2}(?:говорили|обговорювали|розмовляли|вирішили)\b", re.I)
# «Забудь, що я люблю каву», «Забудь про каву» — стерти факт про мене (модель тут новий інструмент не кликала).
# «Забудь урок/правило про …» сюди не потрапляє: його раніше обробляють уроки (lessons.forget_request).
_FORGET_FACT = re.compile(r"^(?:хомі,?\s*)?(?:забудь|видали з пам'яті|викресли з пам'яті)\W+"
                          r"(?:що|про те,? що|про)\s+(.+?)[.!]*$", re.I)


def route(text: str, awaiting: tuple | None = None, page_task: dict | None = None, skills=None,
          now: float | None = None) -> Route | None:
    """None — швидкої команди нема, питаємо Gemma. Порядок перевірок має значення (як і було в main.py)."""
    now = time.time() if now is None else now
    if awaiting and is_yes(text):              # «Закрити Discord?» → «так»
        return Route("confirm", awaiting[0], {**awaiting[1], "confirmed": True})
    if awaiting and is_no(text):
        return Route("decline")
    intent = media_intent(text)                # «постав на паузу»
    if intent:
        return Route("tool", "media", {"action": intent, "times": 3 if "volume" in intent else 1})
    window = window_intent(text)               # «згорни термінал», «перейди в дискорд»
    if window:
        return Route("tool", "window", {"action": window[0], "name": window[1]})
    folder = folder_intent(text)               # «що в папці Games», «відкрий папку …»
    if folder:
        return Route("tool", folder[0], {"name": folder[1]},
                     summarize="Ось що в папці — коротко перекажи голосом:" if folder[0] == "list_folder" else "")
    if wants_selection(text):                  # «переклади виділене» — беремо текст, а не знімок екрана
        return Route("selection")
    target = click_intent(text)                # «натисни на …»
    if target:
        return Route("tool", "click_on_screen", {"text": target})
    age = now - page_task.get("t", 0) if page_task else None
    if page_task and open_page_intent(text, age < 3 * 3600):        # «відкрий її в браузері»
        return Route("tool", "open_page", {})
    if page_status_intent(text):                                     # «як там сторінка?»
        return Route("tool", "page_status", {})
    if page_task and page_retry_intent(text, age < 3600):            # «спробуй ще раз написати сторінку»
        return Route("tool", "make_page", {"name": page_task["name"], "request": page_task["request"]})
    if _FORGET_SKILL.match(text.strip()):
        return Route("forget_skill")
    fact = _FORGET_FACT.match(text.strip().replace("’", "'"))
    if fact:
        return Route("tool", "forget_fact", {"query": fact.group(1)})
    if _RECALL.search(text.replace("’", "'")):         # «про що ми вчора говорили?» — зі щоденника, а не з голови
        return Route("tool", "recall", {"query": text},
                     summarize="Ось що в щоденнику наших розмов — коротко перекажи голосом лише це, нічого не додавай:")
    if skills is not None:
        skill = skills.match(text)             # вивчена навичка: ті самі кроки одразу
        if skill:
            return Route("skill", skill=skill)
    return None
