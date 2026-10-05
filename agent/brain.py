"""Мозок: Gemma через Ollama з характером Хомі, пам'яттю й інструментами."""
import time
from datetime import date

import requests

from .config import REPO_DIR
from .text import extract_prompt, ukr_date
from .tools import Tools

VOICE_RULES = """
ГОЛОСОВИЙ РЕЖИМ
- Зараз ми говоримо голосом: тебе чують через колонки, а мене ти чуєш через мікрофон.
- Відповідай 1–3 короткими реченнями, без списків, емодзі й розмітки.
- Час і дати пиши цифрами (20:04, 5 жовтня 2026) — голос прочитає їх правильно. Не переводь час у слова.
- Якщо щось незрозуміло (мене могло погано розпізнати) — перепитай.
- Для часу, дат, пошуку, пам'яті, музики й програм використовуй свої інструменти.
"""

# Gemma після інструментів любить переходити на «ви». Нагадуємо прямо в результаті інструмента.
STYLE_REMINDER = ("\n\n(Відповідай як Хомі: на «ти», у жіночому роді, коротко, без списків. "
                  "Просто дай відповідь, не розповідай, що користувалась інструментом.)")

MAX_TOOL_ROUNDS = 4
HISTORY_IDLE_RESET_S = 300


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tools = Tools(cfg)
        self.prompt_template = extract_prompt(
            (REPO_DIR / "prompts" / "homyy-system-prompt.md").read_text(encoding="utf-8"))
        self.history: list[dict] = []
        self.last_turn = 0.0

    def _memories(self) -> list[str]:
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
        memories = self._memories()
        if memories:
            prompt += "\nЩО ТИ ЗНАЄШ ПРО МЕНЕ (з пам'яті)\n" + "\n".join(f"- {m}" for m in memories)
        return prompt

    def _chat(self, messages: list[dict]) -> dict:
        o = self.cfg["ollama"]
        payload = {
            "model": o["model"], "messages": messages, "tools": self.tools.schemas(),
            "stream": False, "think": False, "keep_alive": o.get("keep_alive", "30m"),
            "options": {"num_ctx": o.get("num_ctx", 32768), "temperature": o.get("temperature", 0.4)},
        }
        for attempt in range(2):   # перший запит після простою іноді падає, поки модель вантажиться
            r = requests.post(f"{o['url']}/api/chat", timeout=300, json=payload)
            if r.status_code < 500 or attempt == 1:
                break
            time.sleep(3)
        r.raise_for_status()
        return r.json()["message"]

    def ask(self, user_text: str, on_tool=None) -> str:
        if time.time() - self.last_turn > HISTORY_IDLE_RESET_S:
            self.history = []
        self.last_turn = time.time()
        self.history.append({"role": "user", "content": user_text})
        messages = [{"role": "system", "content": self._system_prompt()}, *self.history]

        for _ in range(MAX_TOOL_ROUNDS):
            msg = self._chat(messages)
            calls = msg.get("tool_calls") or []
            if not calls:
                answer = (msg.get("content") or "").strip()
                self.history.append({"role": "assistant", "content": answer})
                return answer
            messages.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": calls})
            for c in calls:
                fn = c["function"]
                if on_tool:
                    on_tool(fn["name"], fn.get("arguments") or {})
                result = self.tools.call(fn["name"], fn.get("arguments") or {})
                messages.append({"role": "tool", "tool_name": fn["name"], "content": result + STYLE_REMINDER})
        return "Ой, я заплуталась з інструментами. Спитай, будь ласка, ще раз."
