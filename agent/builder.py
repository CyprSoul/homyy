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


REVIEW_PROMPT = """Ти прискіплива рецензентка коду. Ось сторінка, яку написали за завданням: {request}

{html}
{errors}
Уважно перевір: чи все із завдання зроблено; чи немає помилок у JavaScript (неоголошені змінні, опечатки в
назвах, обробники на елементи, яких немає); чи працюють усі кнопки й форми; чи зберігаються дані в localStorage;
чи гарно й акуратно виглядає. Якщо все справді добре — відповідай рівно одним словом: OK
Інакше — виправ і відповідай ЛИШЕ повним виправленим кодом файлу від <!DOCTYPE html> до </html>, без пояснень."""

REVIEW_MAX_CHARS = 26000      # більшу сторінку Gemma не перечитає разом із відповіддю (num_ctx)


def js_errors(html: str) -> str:
    """Синтаксичні помилки JavaScript через Node (якщо встановлений) — їх Gemma сама не бачить."""
    import shutil
    import subprocess
    import sys
    import tempfile
    node = shutil.which("node")
    scripts = [m for m in re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I) if m.strip()]
    if not node or not scripts:
        return ""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write("\n;\n".join(scripts))
    try:
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True, timeout=20,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        Path(f.name).unlink(missing_ok=True)
    return "" if r.returncode == 0 else (r.stderr or r.stdout).replace(f.name, "script.js")[-1500:]


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
        self.stage = "пишу"
        self.rounds = int(cfg.get("pages", {}).get("review_rounds", 2))

    @property
    def remote(self) -> bool:
        return bool(self.cfg.get("coder", {}).get("gemini_key"))

    def _write(self, prompt: str) -> str | None:
        """Код пише Gemini (якщо є ключ — сильніший програміст), інакше або при збої — своя Gemma."""
        if self.remote:
            try:
                html = self._write_gemini(prompt)
                if html:
                    return html
                self.log("🛠", "Gemini повернув неповний код — пишу сама")
            except Exception as e:  # noqa: BLE001 — немає інтернету, ліміт, змінилась модель…
                self.log("🛠", f"Gemini недоступний ({str(e)[:150]}) — пишу сама")
        return self._write_local(prompt)

    def _write_gemini(self, prompt: str) -> str | None:
        """Google Gemini API (офіційний, безкоштовний ліміт). Потоком — щоб бачити прогрес."""
        import json
        c = self.cfg["coder"]
        model = c.get("model", "gemini-flash-latest")
        parts: list[str] = []
        last = 0.0
        with requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse",
                headers={"x-goog-api-key": c["gemini_key"]}, timeout=600, stream=True,
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.4}}) as r:
            if r.status_code == 429:
                raise RuntimeError("вичерпано безкоштовний ліміт на сьогодні")
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                chunk = json.loads(line[5:])
                for cand in chunk.get("candidates", [])[:1]:
                    for part in cand.get("content", {}).get("parts", []):
                        if not part.get("thought"):
                            parts.append(part.get("text", ""))
                self.lines = "".join(parts).count("\n")
                if time.time() - last > 3:
                    last = time.time()
                    self._progress()
        return extract_html("".join(parts))

    def _write_local(self, prompt: str) -> str | None:
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
        what = ("Gemini пише код" if self.remote else "пишу код") if self.stage == "пишу" else f"{self.stage} (шукаю й виправляю помилки)"
        return f"Сторінка «{self.busy}»: {what}, минуло {m}:{sec:02d}, зараз {self.lines} рядків."

    def _progress(self, final: str | None = None):
        if final is not None:
            text = final
        else:
            m, sec = divmod(int(time.time() - self.started), 60)
            text = f"🛠 {self.busy} · {self.stage} · {self.lines} рядків · {m}:{sec:02d}"
        if self.on_task:
            try:
                stage = "Gemini пише" if self.remote and self.stage == "пишу" else self.stage
                short = text if final is not None else f"🛠 {stage} {m}:{sec:02d} · {self.lines} р."
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

    def review(self, html: str, request: str, rounds: int) -> str:
        """Режим «якісно»: перечитує свій код, шукає помилки й виправляє (до rounds разів)."""
        for i in range(1, rounds + 1):
            if len(html) > REVIEW_MAX_CHARS and not self.remote:
                self.log("🛠", "сторінка завелика для перевірки цілком — лишаю як є")
                break
            errors = js_errors(html)
            if self.remote and not errors:
                break                     # Gemini пише чисто — свою Gemma ставити йому в рецензенти немає сенсу
            self.stage, self.lines = f"перевіряю {i}/{rounds}", 0
            note = f"\nNode.js знайшов синтаксичну помилку в скрипті — її треба виправити:\n{errors}\n" if errors else ""
            fixed = self._write(REVIEW_PROMPT.format(request=request, html=html, errors=note))
            if fixed is None:
                self.log("🛠", f"перевірка {i}: помилок не знайшла" if not errors else
                         f"перевірка {i}: не змогла виправити")
                if not errors:
                    break
                continue
            self.log("🛠", f"перевірка {i}: виправила ({fixed.count(chr(10))} рядків)")
            html = fixed
        return html

    def start(self, title: str, prompt: str, path: Path, done, request: str = "", rounds: int = 0) -> str:
        if self.busy:
            return f"Я ще пишу сторінку «{self.busy}». Скажу, щойно закінчу."
        self.busy, self.started, self.lines, self._logged = title, time.time(), 0, time.time()
        self.stage = "пишу"
        who = "Gemini пише" if self.remote else "пишу сама"
        self.log("🛠", f"«{title}»: {who}" + (f", перевірка ×{rounds}" if rounds and not self.remote else ""))

        def run():
            t = time.time()
            try:
                html = self._write(prompt)
                if not html:
                    done(f"Не вийшло написати сторінку «{title}»: код вийшов неповний. Спробуй попросити ще раз.")
                    return
                path.write_text(html, encoding="utf-8")          # чернетка — вже є, навіть якщо перевірка впаде
                if rounds:
                    html = self.review(html, request, rounds)
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
        if self.remote:
            return (f"Передала завдання «{title}» програмісту Gemini. Це займе приблизно хвилину; "
                    "коли файл буде готовий — сама скажу й відкрию.")
        how = "хвилин 5–10, бо ще перевірю й виправлю помилки" if rounds else "хвилину-дві"
        return (f"Почала писати сторінку «{title}». Це займе {how}; поки пишу, відповідатиму повільніше. "
                "Коли буде готово — сама скажу й відкрию.")

    def make(self, name: str, request: str, done, quick: bool = False) -> str:
        path = pages_dir() / f"{slug(name)}.html"
        return self.start(name, PAGE_PROMPT.format(request=request), path, done,
                          request=request, rounds=0 if quick else self.rounds)

    def edit(self, request: str, name: str, done) -> str:
        path = self.find(name)
        if path is None:
            return "Ще немає жодної сторінки, яку можна змінити."
        html = path.read_text(encoding="utf-8")
        path.with_suffix(".bak.html").write_text(html, encoding="utf-8")    # попередня версія — про всяк
        return self.start(path.stem, EDIT_PROMPT.format(html=html, request=request), path, done,
                          request=f"(правка) {request}", rounds=min(1, self.rounds))
