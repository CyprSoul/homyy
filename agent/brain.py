"""Мозок: Gemma через Ollama з характером Хомі, пам'яттю й інструментами."""
import re
import time
from datetime import date, datetime

import requests

from .config import REPO_DIR, ollama_options
from .text import claims_action, extract_prompt, ukr_date
from .tools import Tools

VOICE_RULES = """
ГОЛОСОВИЙ РЕЖИМ
- Зараз ми говоримо голосом: тебе чують через колонки, а мене ти чуєш через мікрофон.
- Відповідай 1–3 короткими реченнями, без списків, емодзі й розмітки.
- Час і дати пиши цифрами (20:04, 5 жовтня 2026) — голос прочитає їх правильно. Не переводь час у слова.
- Якщо щось незрозуміло (мене могло погано розпізнати) — перепитай.
- Ти дівчина й у прощаннях теж: «Рада була поговорити», «Я була рада допомогти» — ніколи не «радий».
- Для часу, дат, пошуку, пам'яті, музики, програм і керування комп'ютером використовуй свої інструменти.
- Якщо інструмент каже «ПОТРІБНЕ ПІДТВЕРДЖЕННЯ» — лише коротко перепитай і чекай відповіді.
"""

# Gemma після інструментів любить переходити на «ви». Нагадуємо прямо в результаті інструмента.
STYLE_REMINDER = ("\n\n(Відповідай як Хомі: на «ти», у жіночому роді, коротко, без списків. "
                  "Просто дай відповідь, не розповідай, що користувалась інструментом.)")

MAX_TOOL_ROUNDS = 4
_TIME_WORDS = ("котра", "година", "годин", "час", "зараз", "сьогодні", "дата", "число", "день")
_TRAILING_TIME = re.compile(r"\s*(А )?(зараз|вже|до речі,? зараз)\s+(\d{1,2}:\d{2}|\d{1,2} годин[аи]?)[^.!?]*[.!?]?\s*$",
                            re.IGNORECASE)


_MASC_FIXES = [(re.compile(r"\b(Була|була|Я|я|Я була|я була) радий\b"), r"\1 рада"),
               (re.compile(r"\bБув радий\b"), "Була рада"), (re.compile(r"\bбув радий\b"), "була рада")]


def fix_gender(answer: str) -> str:
    """Gemma інколи збивається на чоловічий рід у прощаннях («Була радий») — Хомі дівчина."""
    for rx, repl in _MASC_FIXES:
        answer = rx.sub(repl, answer)
    return answer


def fix_vocative(answer: str, user: dict) -> str:
    """Звертання так, як подобається господарю: «Ігорю», а не «Ігоре» (або навпаки)."""
    name, voc = user.get("name", ""), user.get("name_vocative")
    if not name or not voc:
        return answer
    for other in {name + "е", name + "ю"} - {voc}:
        answer = re.sub(rf"\b{re.escape(other)}\b", voc, answer)
    return answer


def strip_unasked_time(question: str, answer: str) -> str:
    """Gemma любить додавати «Зараз 23:45.» у кінець — прибираємо, якщо про час не питали."""
    if any(w in question.lower() for w in _TIME_WORDS):
        return answer
    cut = _TRAILING_TIME.sub("", answer).strip()
    return cut or answer
HISTORY_IDLE_RESET_S = 300


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tools = Tools(cfg)
        self.prompt_template = extract_prompt(
            (REPO_DIR / "prompts" / "homyy-system-prompt.md").read_text(encoding="utf-8"))
        self.history: list[dict] = []
        self.last_turn = 0.0
        self.stats: list[str] = []          # таймінги Ollama за останнє питання (для журналу)
        self.last_calls: list[dict] = []
        self.last_results: list[str] = []
        self._mem_cache: list[str] = []
        self._mem_time = 0.0

    def _memories(self) -> list[str]:
        # Пам'ять про тебе змінюється рідко — тримаємо копію 2 хв, щоб не чекати Open WebUI щоразу.
        if time.time() - self._mem_time < 120:
            return self._mem_cache
        self._mem_cache, self._mem_time = self._fetch_memories(), time.time()
        return self._mem_cache

    def _fetch_memories(self) -> list[str]:
        ow = self.cfg.get("openwebui", {})
        if not ow.get("api_key"):
            return []
        try:
            r = requests.get(f"{ow['url']}/api/v1/memories/",
                             headers={"Authorization": f"Bearer {ow['api_key']}"}, timeout=5)
            r.raise_for_status()
            return [m["content"] for m in r.json()]
        except requests.RequestException:
            return []

    def _system_prompt(self) -> str:
        user = self.cfg["user"]
        prompt = (self.prompt_template
                  .replace("{{USER_NAME}}", user.get("name_genitive", user["name"]))
                  .replace("{{CURRENT_DATE}}", ukr_date(date.today())))
        prompt += "\n" + VOICE_RULES
        voc = user.get("name_vocative")
        if voc:
            prompt += f"- Звертаючись до мене, кажи саме «{voc}».\n"
        memories = self._memories()
        if memories:
            prompt += "\nЩО ТИ ЗНАЄШ ПРО МЕНЕ (з пам'яті)\n" + "\n".join(f"- {m}" for m in memories)
        return prompt

    def _chat(self, messages: list[dict]) -> dict:
        o = self.cfg["ollama"]
        payload = {
            "model": o["model"], "messages": messages, "tools": self.tools.schemas(),
            "stream": False, "think": False, "keep_alive": o.get("keep_alive", "30m"),
            "options": ollama_options(self.cfg, temperature=o.get("temperature", 0.4)),
        }
        for attempt in range(2):   # перший запит після простою іноді падає, поки модель вантажиться
            r = requests.post(f"{o['url']}/api/chat", timeout=300, json=payload)
            try:
                self._note_stats(r.json())
            except ValueError:
                pass
            if r.status_code < 500 or attempt == 1:
                break
            time.sleep(3)
        r.raise_for_status()
        return r.json()["message"]

    def _note_stats(self, d: dict):
        """Звідки береться затримка: завантаження моделі, читання промпта чи сама відповідь."""
        ns = 1e9
        load = d.get("load_duration", 0) / ns
        pe, pe_n = d.get("prompt_eval_duration", 0) / ns, d.get("prompt_eval_count", 0)
        ev, ev_n = d.get("eval_duration", 0) / ns, d.get("eval_count", 0)
        if not (load or pe or ev):
            return
        total = d.get("total_duration", 0) / ns
        self.stats.append(f"завантаження {load:.1f} с, промпт {pe_n} ток. за {pe:.1f} с, "
                          f"відповідь {ev_n} ток. за {ev:.1f} с ({ev_n / ev if ev else 0:.0f} ток/с), "
                          f"разом в Ollama {total:.1f} с")

    def direct(self, user_text: str, tool: str, args: dict) -> str:
        """Проста команда без Gemma («постав на паузу»): виконати й запам'ятати в розмові."""
        if time.time() - self.last_turn > HISTORY_IDLE_RESET_S:
            self.history = []
        self.last_turn = time.time()
        self.stats = []
        answer = self.tools.call(tool, args)
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
        return answer

    def direct_reply(self, user_text: str, answer: str) -> str:
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
        return answer

    def ask(self, user_text: str, on_tool=None) -> str:
        if time.time() - self.last_turn > HISTORY_IDLE_RESET_S:
            self.history = []
        self.last_turn = time.time()
        self.stats = []
        self.tools.last_user_text = user_text          # для перевірки «так» на небезпечні дії
        self.history.append({"role": "user", "content": user_text})
        # Час — у поточне питання, а не в інструкції: так незмінні інструкції Ollama бере з кешу.
        now = {"role": "user", "content": f"{user_text}\n\n(Службова довідка, не для озвучення: зараз "
                                          f"{datetime.now():%H:%M}. Називай час лише тоді, коли я про нього питаю "
                                          "— тоді одразу, без інструментів.)"}
        messages = [{"role": "system", "content": self._system_prompt()}, *self.history[:-1], now]

        used_tools, nudged = False, False
        self.last_calls, self.last_results = [], []     # для навичок: що саме зробила на це прохання
        for _ in range(MAX_TOOL_ROUNDS + 1):
            msg = self._chat(messages)
            calls = msg.get("tool_calls") or []
            if not calls and not used_tools and not nudged and claims_action(msg.get("content") or ""):
                # Каже «поставила на паузу», а інструмент не викликала — це неправда. Просимо зробити.
                nudged = True
                messages.append({"role": "assistant", "content": msg.get("content") or ""})
                messages.append({"role": "user", "content": "(Службове: ти ще нічого не зробила — інструмент "
                                 "не викликано. Виконай дію через інструмент, а не словами.)"})
                continue
            if not calls:
                answer = fix_gender(strip_unasked_time(user_text, (msg.get("content") or "").strip()))
                answer = fix_vocative(answer, self.cfg["user"])
                self.history.append({"role": "assistant", "content": answer})
                return answer
            used_tools = True
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for c in calls:
                fn = c["function"]
                if on_tool:
                    on_tool(fn["name"], fn.get("arguments") or {})
                result = self.tools.call(fn["name"], fn.get("arguments") or {})
                self.last_calls.append({"name": fn["name"], "arguments": fn.get("arguments") or {}})
                self.last_results.append(result)
                if fn["name"] == "remember":
                    self._mem_time = 0.0          # новий факт — наступного разу перечитати пам'ять
                messages.append({"role": "tool", "tool_name": fn["name"], "content": result + STYLE_REMINDER})
        return "Ой, я заплуталась з інструментами. Спитай, будь ласка, ще раз."
