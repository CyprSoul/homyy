"""Інструменти, якими Хомі користується сама: час, дати, пошук, пам'ять, медіа, програми."""
import base64
import io
import json
import os
import re
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus

import requests

from .config import ollama_options

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
        # Ненастроєні інтеграції не показуємо: кожен опис Gemma перечитує на кожне питання.
        c = self.cfg
        off = set()
        if not c.get("obsidian", {}).get("vault"):
            off |= {"notes_search", "notes_add"}
        if not c.get("monobank", {}).get("token"):
            off |= {"money_balance", "money_spending"}
        if not (c.get("gmail", {}).get("address") and c.get("gmail", {}).get("app_password")):
            off.add("mail_unread")
        return [s for s in self.base_schemas() + self.pc_schemas(_schema) if s["function"]["name"] not in off]

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
            _schema("play_music", "Увімкнути музику в YouTube Music: «увімкни музику» (без запиту — мої "
                    "вподобані пісні) або конкретну пісню, виконавця, жанр («увімкни Океан Ельзи», "
                    "«увімкни щось спокійне для роботи»).",
                    {"query": {"type": "string", "description": "Що саме; порожньо — мої вподобані пісні"}}),
            _schema("media", "Керування музикою, що ВЖЕ грає: пауза/продовжити, наступна, попередня, гучність. "
                    "Щоб увімкнути музику з нуля — play_music.",
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
            _schema("search_on_site", "Відкрити в браузері пошук на сайті: youtube, google, rozetka, olx, "
                    "wikipedia, youtube music, prom, steam, maps (карти).",
                    {"site": {"type": "string"}, "query": {"type": "string"}}, ["site", "query"]),
            _schema("notes_search", "Знайти в нотатках Obsidian користувача все про тему (його записи, плани, ідеї).",
                    {"query": {"type": "string"}}, ["query"]),
            _schema("notes_add", "Записати нотатку в Obsidian (у файл «Хомі.md» у сховищі нотаток).",
                    {"text": {"type": "string"}}, ["text"]),
            _schema("money_balance", "Баланс картки Monobank."),
            _schema("money_spending", "Скільки витрачено за останні N днів і на що (Monobank).",
                    {"days": {"type": "integer", "description": "1–31"}}, ["days"]),
            _schema("mail_unread", "Нові (непрочитані) листи в Gmail: від кого й про що."),
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

    def _t_play_music(self, query: str = "") -> str:
        """Відкриває YouTube Music так, щоб музика одразу заграла (сторінка «watch», а не головна)."""
        query = (query or "").strip()
        if not query:
            webbrowser.open("https://music.youtube.com/watch?list=LM")      # «Вподобані»
            return "Увімкнула твої вподобані пісні в YouTube Music."
        video = self._first_video(query)
        if video:
            # після пісні YouTube Music сам продовжує схожими (радіо)
            webbrowser.open(f"https://music.youtube.com/watch?v={video}")
            return f"Увімкнула «{query}» в YouTube Music."
        webbrowser.open("https://music.youtube.com/search?q=" + quote_plus(query))
        return f"Відкрила пошук «{query}» в YouTube Music — треба натиснути на пісню, сама не змогла увімкнути."

    @staticmethod
    def _first_video(query: str) -> str | None:
        try:
            r = requests.get("https://www.youtube.com/results", params={"search_query": query}, timeout=8,
                             headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "uk,en;q=0.8"},
                             cookies={"CONSENT": "YES+cb", "SOCS": "CAI"})      # без вікна згоди (ЄС)
            m = re.search(r'"videoId":"([\w-]{11})"', r.text)
            return m.group(1) if m else None
        except requests.RequestException:
            return None

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
            "options": ollama_options(self.cfg, temperature=0.2),
            "messages": [{"role": "user", "content":
                          f"Це знімок екрана користувача. {question}\n"
                          "Відповідай українською, коротко й по суті, лише про те, що справді видно.",
                          "images": [base64.b64encode(buf.getvalue()).decode()]}],
        })
        r.raise_for_status()
        return r.json()["message"]["content"]

    SEARCH_URLS = {
        "youtube": "https://www.youtube.com/results?search_query={}",
        "youtube music": "https://music.youtube.com/search?q={}",
        "google": "https://www.google.com/search?q={}",
        "rozetka": "https://rozetka.com.ua/ua/search/?text={}",
        "olx": "https://www.olx.ua/uk/list/q-{}/",
        "prom": "https://prom.ua/ua/search?search_term={}",
        "wikipedia": "https://uk.wikipedia.org/w/index.php?search={}",
        "steam": "https://store.steampowered.com/search/?term={}",
        "maps": "https://www.google.com/maps/search/{}",
    }
    SITE_ALIASES = {"ютуб": "youtube", "гугл": "google", "розетка": "rozetka", "олх": "olx", "пром": "prom",
                    "вікіпедія": "wikipedia", "стім": "steam", "карти": "maps", "ютуб музика": "youtube music"}

    def _t_search_on_site(self, site: str, query: str) -> str:
        key = site.lower().strip()
        key = self.SITE_ALIASES.get(key, key)
        url = self.SEARCH_URLS.get(key)
        if not url:
            return f"Не знаю, як шукати на «{site}». Вмію: {', '.join(self.SEARCH_URLS)}."
        webbrowser.open(url.format(quote_plus(query)))
        return f"Відкрила пошук «{query}» на {key}."

    def _vault(self) -> Path | None:
        v = self.cfg.get("obsidian", {}).get("vault", "")
        return Path(v) if v and Path(v).is_dir() else None

    def _t_notes_search(self, query: str) -> str:
        vault = self._vault()
        if not vault:
            return "Нотатки Obsidian не підключені: вкажи шлях до сховища в config.toml, розділ [obsidian]."
        words = [w for w in query.lower().split() if len(w) > 2] or [query.lower()]
        hits = []
        for f in vault.rglob("*.md"):
            if ".obsidian" in f.parts or ".trash" in f.parts:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            low = text.lower()
            score = sum(low.count(w) for w in words) + 3 * sum(w in f.stem.lower() for w in words)
            if score:
                i = min((low.find(w) for w in words if w in low), default=0)
                hits.append((score, f.relative_to(vault), text[max(0, i - 200):i + 600].strip()))
        if not hits:
            return f"У нотатках нічого про «{query}»."
        hits.sort(key=lambda h: -h[0])
        return "\n\n".join(f"Нотатка «{p}»:\n{snippet}" for _, p, snippet in hits[:3])

    def _t_notes_add(self, text: str) -> str:
        vault = self._vault()
        if not vault:
            return "Нотатки Obsidian не підключені: вкажи шлях до сховища в config.toml, розділ [obsidian]."
        with open(vault / "Хомі.md", "a", encoding="utf-8") as f:
            f.write(f"\n- {datetime.now():%Y-%m-%d %H:%M} — {text.strip()}")
        return "Записала в нотатку «Хомі»."

    def _mono(self):
        from .services import Monobank
        token = self.cfg.get("monobank", {}).get("token", "")
        if not token:
            return None
        if not hasattr(self, "_mono_client"):
            self._mono_client = Monobank(token)
        return self._mono_client

    def _t_money_balance(self) -> str:
        m = self._mono()
        return m.balance() if m else "Monobank не підключений: додай токен у config.toml, розділ [monobank]."

    def _t_money_spending(self, days: int = 30) -> str:
        m = self._mono()
        return m.spending(days) if m else "Monobank не підключений: додай токен у config.toml, розділ [monobank]."

    def _t_mail_unread(self) -> str:
        from .services import Gmail
        g = self.cfg.get("gmail", {})
        if not g.get("address") or not g.get("app_password"):
            return "Gmail не підключений: додай адресу й пароль застосунку в config.toml, розділ [gmail]."
        return Gmail(g["address"], g["app_password"]).unread()
