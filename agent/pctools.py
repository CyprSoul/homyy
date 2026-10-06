"""Керування Windows: таймер вимкнення, сон, блокування, нагадування, закрити програму,
скриншот, порядок у Завантаженнях, пошук файлів.

Небезпечні дії виконуються лише після твого «так»: перший виклик інструмента лише описує,
що буде зроблено, і Хомі перепитує. Підтвердження перевіряє КОД (не модель): дія спрацює,
тільки якщо попередній крок був саме цим запитом, а твоя наступна фраза — згода.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .text import is_yes

HOME = Path.home()
CATEGORIES = {
    "Картинки": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg"},
    "Документи": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".md"},
    "Відео": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"},
    "Музика": {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"},
    "Архіви": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "Програми": {".exe", ".msi", ".msix", ".appx"},
}
SKIP_SUFFIXES = {".crdownload", ".part", ".tmp", ".partial", ".download"}
SEARCH_DIRS = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]


def category(path: Path) -> str:
    ext = path.suffix.lower()
    for name, exts in CATEGORIES.items():
        if ext in exts:
            return name
    return "Інше"


def downloads_plan(folder: Path) -> dict[str, list[Path]]:
    """Які файли куди переїдуть (лише файли верхнього рівня, недокачані не чіпаємо)."""
    plan: dict[str, list[Path]] = {}
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() not in SKIP_SUFFIXES and not p.name.startswith("."):
            plan.setdefault(category(p), []).append(p)
    return plan


def apply_plan(folder: Path, plan: dict[str, list[Path]]) -> int:
    moved = 0
    for cat, files in plan.items():
        target = folder / cat
        target.mkdir(exist_ok=True)
        for f in files:
            dest = target / f.name
            n = 1
            while dest.exists():                      # нічого не перезаписуємо
                dest = target / f"{f.stem} ({n}){f.suffix}"
                n += 1
            shutil.move(str(f), str(dest))
            moved += 1
    return moved


class PcTools:
    """Домішка до Tools: схеми й виконання інструментів керування ПК."""

    pending: tuple | None = None          # (назва, аргументи), що чекають на «так»
    last_user_text: str = ""
    on_reminder = None                    # main підставляє функцію «сказати вголос»

    def pc_schemas(self, schema) -> list[dict]:
        confirm = {"confirmed": {"type": "boolean",
                                 "description": "true лише після того, як користувач сказав «так» на твоє перепитування"}}
        return [
            schema("shutdown_timer", "Вимкнути комп'ютер через N хвилин (0 — одразу). Потребує підтвердження.",
                   {"minutes": {"type": "integer"}, **confirm}, ["minutes"]),
            schema("cancel_shutdown", "Скасувати заплановане вимкнення комп'ютера."),
            schema("sleep_pc", "Перевести комп'ютер у сон. Потребує підтвердження.", confirm),
            schema("lock_pc", "Заблокувати комп'ютер (екран входу)."),
            schema("click_on_screen", "Натиснути мишкою на напис/кнопку на екрані: «натисни на igorko2018», "
                   "«клікни Грати», «натисни Прийняти». Шукає текст на екрані сам.",
                   {"text": {"type": "string", "description": "Напис на кнопці чи посиланні"}, **confirm}, ["text"]),
            schema("set_reminder", "Таймер/нагадування: через N хвилин Хомі скаже про це вголос.",
                   {"minutes": {"type": "number"}, "text": {"type": "string", "description": "Про що нагадати"}},
                   ["minutes"]),
            schema("close_app", "Закрити програму за назвою (наприклад, discord, steam). Потребує підтвердження.",
                   {"name": {"type": "string"}, **confirm}, ["name"]),
            schema("take_screenshot", "Зробити знімок екрана й зберегти в Зображення\\Хомі."),
            schema("organize_downloads", "Розкласти файли в «Завантаженнях» по папках (Картинки, Документи, Відео…). "
                   "Нічого не видаляє. Потребує підтвердження.", confirm),
            schema("find_file", "Знайти файл за частиною назви на Робочому столі, в Документах, Завантаженнях тощо.",
                   {"query": {"type": "string"}}, ["query"]),
        ]

    # ---- підтвердження ---------------------------------------------------
    def _needs_yes(self, name: str, key, confirmed: bool, describe: str) -> str | None:
        """None — можна виконувати; інакше текст для моделі «спершу перепитай»."""
        # Код, а не модель, перевіряє, що ТИ сказав «так» (Gemma могла перепитати й сама, без інструмента)
        if confirmed and self.pending in (None, (name, key)) and is_yes(self.last_user_text):
            self.pending = None
            return None
        self.pending = (name, key)
        return (f"ПОТРІБНЕ ПІДТВЕРДЖЕННЯ. Нічого ще не зроблено. Коротко спитай користувача: «{describe}?» "
                "Якщо він скаже «так», виклич цей самий інструмент ще раз з confirmed=true.")

    # ---- дії -------------------------------------------------------------
    _RISKY_CLICK = re.compile(r"(видал|delete|remove|купи|buy|придба|оплат|pay|purchase|надісл|send|"
                              r"підтверд|confirm|format|формат|uninstall|скасувати підписку)", re.IGNORECASE)

    def _t_click_on_screen(self, text: str, confirmed: bool = False) -> str:
        from . import screen
        if not screen.available():
            return "Не можу натискати на екрані: немає модуля розпізнавання тексту Windows (winrt)."
        words = screen.screen_words()
        if not words:
            return "Не бачу на екрані жодного напису."
        match = screen.best_match(text, words)
        if not match or match[2] < 0.75:
            seen = ", ".join(w for w, _ in words[:25])
            return f"Не знайшла на екрані «{text}». Видно, зокрема: {seen}."
        label, (x, y), _ = match
        if self._RISKY_CLICK.search(label) or self._RISKY_CLICK.search(text):
            ask = self._needs_yes("click_on_screen", label.lower(), confirmed, f"Точно натиснути «{label}»")
            if ask:
                return ask
        screen.click(x, y)
        return f"Натиснула «{label}»."
    def _t_shutdown_timer(self, minutes: int, confirmed: bool = False) -> str:
        minutes = max(0, min(int(minutes), 24 * 60))
        when = "зараз" if minutes == 0 else f"через {minutes} хв"
        ask = self._needs_yes("shutdown_timer", minutes, confirmed, f"Точно вимкнути комп'ютер {when}")
        if ask:
            return ask
        if sys.platform == "win32":
            subprocess.run(["shutdown", "/s", "/t", str(minutes * 60)], check=False)
        return f"Готово: комп'ютер вимкнеться {when}. Скасувати — «скасуй вимкнення»."

    def _t_cancel_shutdown(self) -> str:
        if sys.platform == "win32":
            subprocess.run(["shutdown", "/a"], check=False)
        return "Вимкнення скасовано."

    def _t_sleep_pc(self, confirmed: bool = False) -> str:
        ask = self._needs_yes("sleep_pc", None, confirmed, "Перевести комп'ютер у сон")
        if ask:
            return ask
        if sys.platform == "win32":
            threading.Timer(3, lambda: subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)).start()
        return "Добре, за 3 секунди засинаю разом із комп'ютером."

    def _t_lock_pc(self) -> str:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        return "Комп'ютер заблоковано."

    def _t_set_reminder(self, minutes: float, text: str = "") -> str:
        minutes = max(0.0, min(float(minutes), 24 * 60))
        what = text.strip() or "час вийшов"

        def fire():
            if self.on_reminder:
                self.on_reminder(f"Нагадую: {what}.")
        threading.Timer(minutes * 60, fire).start()
        at = datetime.fromtimestamp(time.time() + minutes * 60).strftime("%H:%M")
        return f"Таймер поставлено: о {at} нагадаю — {what}."

    def _find_processes(self, name: str) -> list[str]:
        if sys.platform != "win32":
            return []
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False).stdout
        q = name.lower().replace(" ", "").removesuffix(".exe")
        names = {line.split('","')[0].strip('"') for line in out.splitlines() if line}
        protected = {"explorer.exe", "csrss.exe", "winlogon.exe", "svchost.exe", "lsass.exe", "dwm.exe",
                     "services.exe", "system", "python.exe", "pythonw.exe", "ollama.exe"}
        return sorted(n for n in names if q in n.lower() and n.lower() not in protected)

    def _t_close_app(self, name: str, confirmed: bool = False) -> str:
        procs = self._find_processes(name)
        if sys.platform == "win32" and not procs:
            return f"Не бачу запущеної програми «{name}»."
        ask = self._needs_yes("close_app", name.lower(), confirmed,
                              f"Закрити {', '.join(procs) or name}? Незбережене може пропасти")
        if ask:
            return ask
        for p in procs:
            subprocess.run(["taskkill", "/IM", p, "/T"], check=False, capture_output=True)
        time.sleep(2)
        # Discord, Steam, Telegram на «закрити» лише ховаються в трей — тоді закриваємо примусово
        left = [p for p in self._find_processes(name) if p in procs] if sys.platform == "win32" else []
        for p in left:
            subprocess.run(["taskkill", "/IM", p, "/T", "/F"], check=False, capture_output=True)
        return f"Закрила: {', '.join(procs) or name}."

    def _t_take_screenshot(self) -> str:
        from PIL import ImageGrab
        folder = HOME / "Pictures" / "Хомі"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"скриншот {datetime.now():%Y-%m-%d %H-%M-%S}.png"
        ImageGrab.grab().save(path)
        return f"Знімок збережено: {path}"

    def _t_organize_downloads(self, confirmed: bool = False) -> str:
        folder = HOME / "Downloads"
        plan = downloads_plan(folder)
        total = sum(len(v) for v in plan.values())
        if total == 0:
            return "У Завантаженнях і так порядок — окремих файлів немає."
        summary = ", ".join(f"{cat}: {len(v)}" for cat, v in sorted(plan.items()))
        ask = self._needs_yes("organize_downloads", total, confirmed,
                              f"Розкласти {total} файлів у Завантаженнях по папках ({summary})")
        if ask:
            return ask
        moved = apply_plan(folder, plan)
        return f"Готово: розклала {moved} файлів ({summary}). Нічого не видалено."

    def _t_find_file(self, query: str) -> str:
        q, found, seen = query.lower().strip(), [], 0
        for d in SEARCH_DIRS:
            for root, dirs, files in os.walk(HOME / d):
                dirs[:] = [x for x in dirs if not x.startswith(".") and x != "node_modules"]
                for f in files:
                    seen += 1
                    if q in f.lower():
                        found.append(os.path.join(root, f))
                if len(found) >= 5 or seen > 50000:
                    break
        if not found:
            return f"Не знайшла файлів зі словом «{query}»."
        return "Знайшла:\n" + "\n".join(found[:5])
