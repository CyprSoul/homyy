"""Хомі пише сторінки сама: трекер тренувань, калькулятор, таймер, список — одним HTML-файлом.

Gemma пише код у фоні (≈1–2 хв: це той самий мозок, окремої моделі немає), файл лягає в
Документи\\Хомі\\сторінки, відкривається в браузері, і Хомі каже «готово». Дані сторінка тримає
в localStorage браузера — нічого не йде в інтернет. Правки: «зроби кнопки більшими» → edit.
"""
import re
import threading
import time
import webbrowser
from pathlib import Path

import requests

from .config import ollama_options

PAGE_PROMPT = """Ти досвідчена веб-розробниця. Напиши ОДИН повний файл index.html за завданням нижче.
Вимоги:
- Усе в одному файлі: HTML, CSS у <style>, JavaScript у <script>. Без зовнішніх бібліотек, шрифтів і картинок з інтернету.
- Сучасний гарний дизайн: темна тема, акуратні відступи, заокруглення, плавні переходи, зручно на великому екрані.
- Увесь текст на сторінці — українською.
- Якщо сторінка щось зберігає (записи, налаштування, прогрес) — у localStorage, щоб не губилося після закриття.
- Графіки, якщо потрібні, малюй самостійно на <canvas> або SVG.
- Код має працювати одразу, без помилок, з відкриття файлу в браузері.
Відповідай ЛИШЕ кодом файлу від <!DOCTYPE html> до </html>, без пояснень.

Завдання: {request}"""

EDIT_PROMPT = """Ти досвідчена веб-розробниця. Ось поточний файл сторінки:

{html}

Внеси зміну: {request}
Збережи все, що працювало, і дані в localStorage (ті самі ключі). Відповідай ЛИШЕ повним новим кодом файлу
від <!DOCTYPE html> до </html>, без пояснень."""


def pages_dir() -> Path:
    d = Path.home() / "Documents" / "Хомі" / "сторінки"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug(name: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", name.strip().lower()).strip().replace(" ", "-")
    return (s or "сторінка")[:60]


def extract_html(text: str) -> str | None:
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    if m and "<html" in m.group(1).lower():
        text = m.group(1)
    start = text.lower().find("<!doctype")
    if start < 0:
        start = text.lower().find("<html")
    end = text.lower().rfind("</html>")
    if start < 0 or end < 0:
        return None
    return text[start:end + len("</html>")]


class PageBuilder:
    def __init__(self, cfg: dict, log=print):
        self.cfg = cfg
        self.log = log
        self.busy: str | None = None
        self.last: Path | None = None
        self.on_task = None                 # рядок прогресу під сферою (main підставляє)
        self.started = 0.0
        self.lines = 0
        self._logged = 0.0

    def _write(self, prompt: str) -> str | None:
        """Пише потоком: так видно прогрес (рядки, час) — у журналі, під сферою й на питання «як там?»."""
        import json
        o = self.cfg["ollama"]
        parts: list[str] = []
        last = 0.0
        with requests.post(f"{o['url']}/api/chat", timeout=900, stream=True, json={
                "model": o["model"], "stream": True, "think": False, "keep_alive": o.get("keep_alive", "24h"),
                "options": ollama_options(self.cfg, temperature=0.4, num_predict=8000),
                "messages": [{"role": "user", "content": prompt}]}) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                parts.append(chunk.get("message", {}).get("content", ""))
                self.lines = "".join(parts).count("\n")
                if time.time() - last > 3:
                    last = time.time()
                    self._progress()
                if chunk.get("done"):
                    break
        return extract_html("".join(parts))

    def status(self) -> str:
        if not self.busy:
            return "Зараз нічого не пишу."
        m, sec = divmod(int(time.time() - self.started), 60)
        return f"Пишу «{self.busy}»: {m}:{sec:02d}, вже {self.lines} рядків коду."

    def _progress(self, final: str | None = None):
        if final is not None:
            text = final
        else:
            m, sec = divmod(int(time.time() - self.started), 60)
            text = f"🛠 {self.busy} · {self.lines} рядків · {m}:{sec:02d}"
        if self.on_task:
            try:
                short = text if final is not None else f"🛠 пишу {m}:{sec:02d} · {self.lines} р."
                self.on_task(short)
            except Exception:  # noqa: BLE001
                pass
        if final is None and time.time() - self._logged > 20:
            self._logged = time.time()
            self.log("🛠", text)

    def find(self, name: str = "") -> Path | None:
        pages = [p for p in pages_dir().glob("*.html") if not p.name.endswith(".bak.html")]
        if not name:
            return self.last or max(pages, key=lambda p: p.stat().st_mtime, default=None)
        want = slug(name)
        exact = [p for p in pages if p.stem == want]
        return exact[0] if exact else next((p for p in pages if want in p.stem or p.stem in want), None)

    def start(self, title: str, prompt: str, path: Path, done) -> str:
        if self.busy:
            return f"Я ще пишу сторінку «{self.busy}». Скажу, щойно закінчу."
        self.busy, self.started, self.lines, self._logged = title, time.time(), 0, time.time()
        self.log("🛠", f"почала писати «{title}»")

        def run():
            t = time.time()
            try:
                html = self._write(prompt)
                if not html:
                    done(f"Не вийшло написати сторінку «{title}»: код вийшов неповний. Спробуй попросити ще раз.")
                    return
                path.write_text(html, encoding="utf-8")
                self.last = path
                webbrowser.open(path.as_uri())
                self.log("🛠", f"сторінка «{title}» готова за {time.time() - t:.0f} с: {path}")
                done(f"Готово, сторінка «{title}» відкрита в браузері.")
            except Exception as e:  # noqa: BLE001
                self.log("🛠", f"не вийшло: {e}")
                done(f"Не вийшло написати сторінку «{title}».")
            finally:
                self.busy = None
                self._progress(final="")
        threading.Thread(target=run, daemon=True).start()
        return (f"Почала писати сторінку «{title}». Це займе хвилину-дві; поки пишу, відповідатиму повільніше. "
                "Коли буде готово — сама скажу й відкрию.")

    def make(self, name: str, request: str, done) -> str:
        path = pages_dir() / f"{slug(name)}.html"
        return self.start(name, PAGE_PROMPT.format(request=request), path, done)

    def edit(self, request: str, name: str, done) -> str:
        path = self.find(name)
        if path is None:
            return "Ще немає жодної сторінки, яку можна змінити."
        html = path.read_text(encoding="utf-8")
        path.with_suffix(".bak.html").write_text(html, encoding="utf-8")    # попередня версія — про всяк
        return self.start(path.stem, EDIT_PROMPT.format(html=html, request=request), path, done)
