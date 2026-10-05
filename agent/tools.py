"""Інструменти, якими Хомі користується сама: час, дати, пошук, пам'ять, медіа, програми."""
import base64
import io
import json
import os
import sys
import webbrowser
from datetime import date, datetime

import requests

from .pctools import PcTools
from .text import date_diff, ukr_date

# Віртуальні клавіші Windows для медіа.
_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
       "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}


def _schema(name, description, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


class Tools(PcTools):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.apps = {k.lower(): v for k, v in cfg.get("apps", {}).items()}

    # ---- опис для моделі -------------------------------------------------
    def schemas(self) -> list[dict]:
        return self.base_schemas() + self.pc_schemas(_schema)

    def base_schemas(self) -> list[dict]:
        apps = ", ".join(self.apps) or "немає"
        return [
            _schema("current_datetime", "Поточні дата й час."),
            _schema("date_difference",
                    "Точна різниця між двома датами в роках, місяцях і днях. Для віку, «скільки днів до…» тощо.",
                    {"from_date": {"type": "string", "description": "YYYY-MM-DD"},
                     "to_date": {"type": "string", "description": "YYYY-MM-DD; порожньо = сьогодні"}},
                    ["from_date"]),
            _schema("web_search", "Пошук в інтернеті: свіжі новини, погода, ціни, факти.",
                    {"query": {"type": "string"}}, ["query"]),
            _schema("remember", "Запам'ятати важливий довготривалий факт про користувача. "
                    "Пиши від третьої особи: «Користувач любить…».",
                    {"fact": {"type": "string"}}, ["fact"]),
            _schema("media", "Керування музикою й звуком на ПК.",
                    {"action": {"type": "string", "enum": list(_VK)},
                     "times": {"type": "integer", "description": "Скільки разів натиснути (для гучності)"}},
                    ["action"]),
            _schema("open_app", f"Відкрити програму чи сайт зі списку: {apps}.",
                    {"name": {"type": "string"}}, ["name"]),
            _schema("mark_game", "Позначити програму, яка зараз на екрані, як гру (у ній Хомі звільняє "
                    "відеокарту) або як НЕ гру. Коли кажуть «це гра» / «це не гра».",
                    {"is_game": {"type": "boolean"}}, ["is_game"]),
            _schema("look_at_screen", "Подивитися на екран користувача й відповісти на питання про те, що там: "
                    "«що в мене на екрані», «що це за помилка», «переклади, що тут написано».",
                    {"question": {"type": "string", "description": "Що саме треба з'ясувати на екрані"}},
                    ["question"]),
            _schema("open_website", "Відкрити сайт у браузері.",
                    {"url": {"type": "string", "description": "Повна адреса https://…"}}, ["url"]),
        ]

    # ---- виконання -------------------------------------------------------
    def call(self, name: str, args: dict) -> str:
        fn = getattr(self, f"_t_{name}", None)
        if fn is None:
            return f"Невідомий інструмент: {name}"
        try:
            return fn(**(args or {}))
        except Exception as e:  # модель має дізнатися про помилку, а не «впасти»
            return f"Помилка інструмента {name}: {e}"

    def _t_current_datetime(self) -> str:
        now = datetime.now()
        return f"Зараз {ukr_date(now.date())}, {now:%H:%M}."

    def _t_date_difference(self, from_date: str, to_date: str = "") -> str:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date) if to_date else date.today()
        return json.dumps(date_diff(start, end), ensure_ascii=False)

    def _t_web_search(self, query: str) -> str:
        r = requests.get(f"{self.cfg['search']['url']}/search",
                         params={"q": query, "format": "json"}, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])[:3]
        if not results:
            return "Нічого не знайдено."
        return "\n\n".join(f"{x.get('title', '')}\n{x.get('content', '')[:400]}\nДжерело: {x.get('url', '')}"
                           for x in results)

    def _t_remember(self, fact: str) -> str:
        ow = self.cfg.get("openwebui", {})
        if not ow.get("api_key"):
            return "Пам'ять не підключена (немає API-ключа Open WebUI)."
        r = requests.post(f"{ow['url']}/api/v1/memories/add", json={"content": fact},
                          headers={"Authorization": f"Bearer {ow['api_key']}"}, timeout=10)
        r.raise_for_status()
        return "Записано в пам'ять."

    def _t_media(self, action: str, times: int = 1) -> str:
        if action not in _VK:
            return f"Невідома дія: {action}"
        times = max(1, min(int(times or 1), 25))
        if sys.platform == "win32":
            import ctypes
            for _ in range(times):
                ctypes.windll.user32.keybd_event(_VK[action], 0, 0, 0)
                ctypes.windll.user32.keybd_event(_VK[action], 0, 2, 0)
        return f"Виконано: {action} ×{times}."

    def _t_open_app(self, name: str) -> str:
        target = self.apps.get(name.lower().strip())
        if not target:
            return f"Такої програми немає в списку. Доступні: {', '.join(self.apps)}."
        if sys.platform == "win32":
            os.startfile(target)
        return f"Відкрила {name}."

    def _t_open_website(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return "Можна відкривати лише адреси, що починаються з http:// або https://."
        webbrowser.open(url)
        return f"Відкрила {url}."

    def _t_mark_game(self, is_game: bool) -> str:
        from .gamewatch import foreground, remember
        exe, _ = foreground()
        if not exe or exe.lower() in ("python.exe", "pythonw.exe", "powershell.exe"):
            return "Не бачу, яка програма зараз на екрані."
        remember(exe, bool(is_game))
        return f"Запам'ятала: {exe} — {'гра' if is_game else 'не гра'}."

    def _t_look_at_screen(self, question: str) -> str:
        """Знімок екрана → Gemma (вона бачить картинки) → текстова відповідь. Знімок нікуди не йде з ПК."""
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=False).convert("RGB")
        img.thumbnail((1600, 1600))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        o = self.cfg["ollama"]
        r = requests.post(f"{o['url']}/api/chat", timeout=180, json={
            "model": o["model"], "stream": False, "think": False, "keep_alive": o.get("keep_alive", "24h"),
            "options": {"num_ctx": o.get("num_ctx", 32768), "temperature": 0.2},
            "messages": [{"role": "user", "content":
                          f"Це знімок екрана користувача. {question}\n"
                          "Відповідай українською, коротко й по суті, лише про те, що справді видно.",
                          "images": [base64.b64encode(buf.getvalue()).decode()]}],
        })
        r.raise_for_status()
        return r.json()["message"]["content"]
