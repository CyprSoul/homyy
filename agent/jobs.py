"""Фонові задачі Хомі в одному місці: нагадування й таймер вимкнення ПК.

Звідси береться правда для моделі («що в мене заплановано?», «що ти зараз робиш?») і для швидких команд
«які нагадування», «скасуй нагадування про воду». Раніше нагадування були просто таймерами в пам'яті:
модель про них не знала, скасувати не можна було, а після перезапуску Хомі вони мовчки зникали.
Тепер вони в agent/jobs.json і переживають перезапуск; пропущені, поки Хомі була вимкнена, — озвучуються.
"""
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

JOBS_FILE = Path(__file__).resolve().parent / "jobs.json"
KEEP_DONE_S = 24 * 3600            # виконані/скасовані тримаємо добу — щоб відповісти «вже нагадала»


def at(t: float) -> str:
    d = datetime.fromtimestamp(t)
    return f"{d:%H:%M}" if d.date() == datetime.now().date() else f"{d:%d.%m %H:%M}"


class JobBook:
    def __init__(self, path: Path | None = None, on_due=None):
        self.path = path or JOBS_FILE
        self.on_due = on_due                 # on_due(job) — настав час нагадування (main каже вголос)
        self.lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}
        self.jobs: list[dict] = self._load()

    # ---- збереження ----------------------------------------------------
    def _load(self) -> list[dict]:
        try:
            jobs = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        now = time.time()
        return [j for j in jobs if j.get("status") == "active" or now - j.get("ended", now) < KEEP_DONE_S]

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.jobs, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ---- задачі --------------------------------------------------------
    def add_reminder(self, minutes: float, text: str) -> dict:
        job = {"id": uuid.uuid4().hex[:8], "kind": "reminder", "title": text, "due": time.time() + minutes * 60,
               "status": "active"}
        with self.lock:
            self.jobs.append(job)
            self._save()
        self._arm(job)
        return job

    def add_shutdown(self, minutes: float) -> dict:
        """Таймер вимкнення в Windows один — новий замінює старий."""
        self.cancel(kind="shutdown")
        job = {"id": uuid.uuid4().hex[:8], "kind": "shutdown", "title": "вимкнення комп'ютера",
               "due": time.time() + minutes * 60, "status": "active"}
        with self.lock:
            self.jobs.append(job)
            self._save()
        return job

    def cancel(self, kind: str | None = None, query: str = "") -> list[dict]:
        """Скасовує активні задачі цього виду, у назві яких є всі ключові слова запиту."""
        keys = [w[:max(3, min(5, len(w) - 2))] for w in re.findall(r"[\w']+", (query or "").lower())
                if len(w) >= 3 and w not in ("про", "що", "нагадування", "таймер", "всі", "усі", "мені")]
        done = []
        with self.lock:
            for j in self.jobs:
                if j["status"] != "active" or (kind and j["kind"] != kind):
                    continue
                if keys and not all(k in j["title"].lower() for k in keys):
                    continue
                j["status"], j["ended"] = "cancelled", time.time()
                timer = self._timers.pop(j["id"], None)
                if timer:
                    timer.cancel()
                done.append(j)
            if done:
                self._save()
        return done

    def active(self) -> list[dict]:
        now = time.time()
        return sorted((j for j in self.jobs if j["status"] == "active" and j["due"] > now - 60),
                      key=lambda j: j["due"])

    def describe(self) -> str:
        """«нагадування о 18:30 — вода; вимкнення комп'ютера о 23:00» або порожньо."""
        parts = []
        for j in self.active():
            parts.append(f"нагадування о {at(j['due'])} — {j['title']}" if j["kind"] == "reminder"
                         else f"{j['title']} о {at(j['due'])}")
        return "; ".join(parts)

    # ---- таймери -------------------------------------------------------
    def _arm(self, job: dict):
        timer = threading.Timer(max(0.0, job["due"] - time.time()), self._fire, [job["id"]])
        timer.daemon = True
        self._timers[job["id"]] = timer
        timer.start()

    def _fire(self, job_id: str):
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id and j["status"] == "active"), None)
            if job is None:
                return
            job["status"], job["ended"] = "done", time.time()
            self._timers.pop(job_id, None)
            self._save()
        if self.on_due:
            self.on_due(job)

    def arm_all(self) -> list[dict]:
        """На старті Хомі: майбутні нагадування — знову чекають свого часу; ті, що минули, поки Хомі була
        вимкнена, повертаємо (main скаже про них). Таймер вимкнення живе у Windows — лише запис."""
        missed, now = [], time.time()
        for j in list(self.jobs):
            if j["status"] != "active":
                continue
            if j["kind"] == "reminder" and j["due"] > now:
                self._arm(j)
            elif j["due"] <= now:
                j["status"], j["ended"] = "missed" if j["kind"] == "reminder" else "done", now
                if j["kind"] == "reminder":
                    missed.append(j)
        self._save()
        return missed
