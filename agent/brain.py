"""Мозок: Gemma через Ollama з характером Хомі, пам'яттю й інструментами."""
import json
import re
import time
from datetime import date, datetime

import requests

from .config import REPO_DIR, ollama_options
from .text import (claims_action, extract_prompt, fix_russisms, looks_ukrainian, promises_more, ukr_date,
                   wants_other_language)
from .tools import Tools

VOICE_RULES = """
ГОЛОСОВИЙ РЕЖИМ — ЦЕ ГОЛОВНЕ
- Ми говоримо голосом. Відповідай 1–2 короткими реченнями, як у живій розмові. Без списків, емодзі, розмітки й «лекцій».
- ДІЙ, а не пропонуй. Просять пошукати, відкрити, показати, увімкнути — одразу роби інструментом і коротко кажи результат.
  Ніколи не закінчуй словами «Хочеш, я пошукаю/знайду/покажу?» — просто зроби це.
- «Покажи», «відкрий і покажи» — відкрий у браузері (search_on_site або open_website), а не розповідай.
- Перепитуй лише тоді, коли прохання зовсім незрозуміле. Якщо зрозуміло хоч приблизно — роби найімовірніше.
- Не хвали ідеї й не пиши вступів («Це звучить як дуже крута ідея…») — одразу по суті.
- Час і дати пиши цифрами (20:04, 5 жовтня 2026) — голос прочитає їх правильно.
- Ти дівчина й у прощаннях теж: «Рада була поговорити» — ніколи не «радий».
- Якщо інструмент каже «ПОТРІБНЕ ПІДТВЕРДЖЕННЯ» — лише коротко перепитай і чекай відповіді.
"""

# Gemma після інструментів любить переходити на «ви». Нагадуємо прямо в результаті інструмента.
STYLE_REMINDER = ("\n\n(Відповідай як Хомі: на «ти», у жіночому роді, коротко, без списків. "
                  "Просто дай відповідь, не розповідай, що користувалась інструментом.)")

MAX_TOOL_ROUNDS = 4
DEEP = re.compile(r"(подумай|поміркуй|подумати|обміркуй|розміркуй|проаналізуй|детально розбери|"
                  r"ретельно|глибоко|як слід подумай|добре подумай)", re.IGNORECASE)
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


class Cancelled(Exception):
    """Відповідь скасована: людина ще говорила, поки Gemma думала."""


class SentenceStream:
    """Збирає шматочки тексту від Gemma в речення й віддає їх голосу по одному.

    Речення, що звучить як порожня обіцянка, «я зробила» без дії чи не українською, не
    озвучується одразу — Хомі спершу перевірить усю відповідь (як і без потоку).
    """

    def __init__(self, brain: "Brain", user_text: str, emit):
        self.brain, self.user_text, self.emit = brain, user_text, emit
        self.buf, self.held, self.spoken = "", [], []
        self.hold = False
        self.used_tools = False

    def feed(self, piece: str):
        self.buf += piece
        while True:
            m = re.search(r"[.!?…](?:[\"»)])?\s+", self.buf)
            if not m:
                return
            sent, self.buf = self.buf[:m.end()].strip(), self.buf[m.end():]
            self._sentence(sent)

    def _risky(self, sent: str) -> bool:
        if promises_more(sent) or (not self.used_tools and claims_action(sent)):
            return True
        return (len(sent.split()) >= 4 and not looks_ukrainian(sent)
                and not wants_other_language(self.user_text))

    def _sentence(self, sent: str):
        if self.hold or self._risky(sent):
            self.hold = True
            self.held.append(sent)
            return
        sent = self.brain.polish(self.user_text, sent)
        if sent:
            self.spoken.append(sent)
            self.emit(sent)

    def new_round(self, used_tools: bool):
        """Нова відповідь Gemma (після інструментів чи прохання виправитись)."""
        self.buf, self.held, self.hold, self.used_tools = "", [], False, used_tools

    def flush(self):
        """Кінець відповіді: доозвучити хвіст (і притримане, якщо перевірка все ж пройшла)."""
        rest = self.held + ([self.buf.strip()] if self.buf.strip() else [])
        self.buf, self.held, self.hold = "", [], False
        for sent in rest:
            sent = self.brain.polish(self.user_text, sent)
            if sent:
                self.spoken.append(sent)
                self.emit(sent)


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tools = Tools(cfg)
        self.prompt_template = extract_prompt(
            (REPO_DIR / "prompts" / "homyy-system-prompt.md").read_text(encoding="utf-8"))
        try:   # «як говорять люди» — живі розмовні ситуації, лише для голосу
            self.cases = extract_prompt((REPO_DIR / "prompts" / "dialog-cases.md").read_text(encoding="utf-8"))
        except OSError:
            self.cases = ""
        from .lessons import LessonBook
        self.lessons = LessonBook()
        self.last_exchange: tuple[str, str] | None = None
        self.history: list[dict] = []
        self.last_turn = 0.0
        self.stats: list[str] = []          # таймінги Ollama за останнє питання (для журналу)
        self.last_calls: list[dict] = []
        self.last_results: list[str] = []
        self.deep = False
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
        if self.cases:
            prompt += "\n" + self.cases + "\n"
        prompt += self.lessons.prompt_block()
        voc = user.get("name_vocative")
        if voc:
            prompt += f"- Звертаючись до мене, кажи саме «{voc}».\n"
        memories = self._memories()
        if memories:
            prompt += "\nЩО ТИ ЗНАЄШ ПРО МЕНЕ (з пам'яті)\n" + "\n".join(f"- {m}" for m in memories)
        return prompt

    def _chat(self, messages: list[dict], on_delta=None, cancel=None) -> dict:
        if on_delta is not None:
            return self._chat_stream(messages, on_delta, cancel)
        o = self.cfg["ollama"]
        payload = {
            "model": o["model"], "messages": messages, "tools": self.tools.schemas(),
            "stream": False, "think": self.deep, "keep_alive": o.get("keep_alive", "30m"),
            "options": ollama_options(self.cfg, temperature=o.get("temperature", 0.4),
                                      # голосом — коротко; у режимі «подумай» ще й місце на роздуми
                                      num_predict=int(o.get("voice_max_tokens", 160)) + (3000 if self.deep else 0)),
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
        data = r.json()
        self.cut_short = data.get("done_reason") == "length"
        return data["message"]

    def _payload(self, messages: list[dict], stream: bool) -> dict:
        o = self.cfg["ollama"]
        return {
            "model": o["model"], "messages": messages, "tools": self.tools.schemas(),
            "stream": stream, "think": self.deep, "keep_alive": o.get("keep_alive", "30m"),
            "options": ollama_options(self.cfg, temperature=o.get("temperature", 0.4),
                                      num_predict=int(o.get("voice_max_tokens", 160)) + (3000 if self.deep else 0)),
        }

    def _chat_stream(self, messages: list[dict], on_delta, cancel=None) -> dict:
        """Те саме, що _chat, але текст іде шматочками в on_delta, поки Gemma ще пише."""
        o = self.cfg["ollama"]
        content, calls = [], []
        with requests.post(f"{o['url']}/api/chat", timeout=300, stream=True,
                           json=self._payload(messages, True)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if cancel is not None and cancel():
                    raise Cancelled()
                if not line:
                    continue
                d = json.loads(line)
                m = d.get("message") or {}
                if m.get("tool_calls"):
                    calls += m["tool_calls"]
                piece = m.get("content") or ""
                if piece:
                    content.append(piece)
                    on_delta(piece)
                if d.get("done"):
                    self._note_stats(d)
                    self.cut_short = d.get("done_reason") == "length"
        return {"content": "".join(content), "tool_calls": calls}

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
        self.last_exchange = (user_text, answer)
        return answer

    def direct_reply(self, user_text: str, answer: str) -> str:
        self.history += [{"role": "user", "content": user_text}, {"role": "assistant", "content": answer}]
        self.last_exchange = (user_text, answer)
        return answer

    def learn(self, request: str, answer: str, reaction: str) -> str | None:
        """Сформулювати правило з твого зауваження й записати в уроки. Повертає правило або None."""
        from .lessons import LESSON_PROMPT
        o = self.cfg["ollama"]
        try:
            r = requests.post(f"{o['url']}/api/chat", timeout=60, json={
                "model": o["model"], "stream": False, "think": False, "keep_alive": o.get("keep_alive", "24h"),
                "options": ollama_options(self.cfg, temperature=0.2, num_predict=80),
                "messages": [{"role": "user", "content": LESSON_PROMPT.format(
                    request=request, answer=answer, feedback=reaction)}]})
            r.raise_for_status()
            rule = (r.json()["message"].get("content") or "").strip().strip('"«»')
        except (requests.RequestException, ValueError, KeyError):
            return None
        if not rule or rule.upper().startswith("NONE"):
            return None
        rule = fix_russisms(rule.splitlines()[0])
        self.lessons.add(rule, source=f"{request} → {reaction}")
        return rule

    GREET_FILE = REPO_DIR / "agent" / "greetings.json"

    def greet(self) -> str | None:
        """Привітання після запуску — своїми словами, з урахуванням часу й пам'яті, щоразу інакше."""
        import json as _json
        now = datetime.now()
        part = ("ніч" if now.hour < 5 else "ранок" if now.hour < 12 else "день" if now.hour < 18
                else "вечір" if now.hour < 23 else "ніч")
        try:
            recent = _json.loads(self.GREET_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recent = []
        ask = (f"(Службове: тебе щойно запустили — ти повністю завантажилась і готова. Зараз {now:%H:%M}, "
               f"{part}, {ukr_date(now.date())}. Привітайся зі мною одним-двома короткими реченнями — "
               "по-своєму, живо, як подруга, з твоїм характером; можеш згадати щось із пам'яті про мене "
               "чи пору дня. Дай відчути, що ти вже тут і готова. Без шаблонів на кшталт «Я готова до роботи».")
        if recent:
            ask += " Не повторюй і не перефразовуй ці привітання: " + " | ".join(recent[-6:])
        ask += ")"
        o = self.cfg["ollama"]
        try:
            r = requests.post(f"{o['url']}/api/chat", timeout=90, json={
                "model": o["model"], "stream": False, "think": False, "keep_alive": o.get("keep_alive", "24h"),
                "options": ollama_options(self.cfg, temperature=0.95, num_predict=80),
                "messages": [{"role": "system", "content": self._system_prompt()},
                             {"role": "user", "content": ask}]})
            r.raise_for_status()
            text = (r.json()["message"].get("content") or "").strip()
        except (requests.RequestException, ValueError, KeyError):
            return None
        if not text or not looks_ukrainian(text):
            return None
        text = self.polish("", text)
        try:
            self.GREET_FILE.write_text(_json.dumps((recent + [text])[-10:], ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return text

    def polish(self, user_text: str, text: str) -> str:
        """Ті самі виправлення, що й для цілої відповіді: час, рід, звертання, русизми."""
        text = fix_gender(strip_unasked_time(user_text, text))
        return fix_russisms(fix_vocative(text, self.cfg["user"])).strip()

    def ask(self, user_text: str, on_tool=None, on_sentence=None, cancel=None) -> str:
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

        used_tools, nudged, lang_nudged = False, False, False
        # «Подумай гарненько…» — Gemma спершу міркує сама з собою (повільніше, 10–30 с, але розумніше)
        self.deep = bool(DEEP.search(user_text))
        self.last_calls, self.last_results = [], []     # для навичок: що саме зробила на це прохання
        stream = SentenceStream(self, user_text, on_sentence) if on_sentence else None
        for _ in range(MAX_TOOL_ROUNDS + 2):
            if stream:
                stream.new_round(used_tools)
                msg = self._chat(messages, on_delta=stream.feed, cancel=cancel)
            else:
                msg = self._chat(messages)
            calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            if (not calls and not lang_nudged and content and not looks_ukrainian(content)
                    and not wants_other_language(user_text)):
                # Gemma перескочила на російську/англійську — просимо переказати українською
                lang_nudged = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "(Службове: відповідай лише українською мовою. "
                                 "Перекажи свою відповідь українською.)"})
                continue
            if not calls and not nudged and ((not used_tools and claims_action(content)) or promises_more(content)):
                # Каже «поставила на паузу» без інструмента, або обіцяє «зараз загляну» і завершує —
                # після відповіді нічого не станеться. Просимо зробити зараз або чесно сказати, що не вміє.
                nudged = True
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": "(Службове: після твоєї відповіді ти вже нічого не "
                                 "зробиш сама — у тебе немає «потім». Зроби обіцяне ЗАРАЗ через інструменти й дай "
                                 "результат. Якщо жоден інструмент цього не вміє — чесно скажи, що не вмієш.)"})
                continue
            if not calls:
                text_ = (msg.get("content") or "").strip()
                if getattr(self, "cut_short", False):          # уперлася в ліміт — без обірваного речення
                    m = re.match(r"(?s)(.*[.!?…])", text_)
                    text_ = m.group(1) if m else text_
                    if stream:
                        stream.buf = ""                       # обірваний хвіст не озвучуємо
                if stream:
                    stream.flush()
                    answer = " ".join(stream.spoken) or self.polish(user_text, text_)
                else:
                    answer = self.polish(user_text, text_)
                self.history.append({"role": "assistant", "content": answer})
                self.last_exchange = (user_text, answer)
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
