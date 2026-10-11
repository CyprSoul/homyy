"""Набір перевірок мозку Хомі на справжній моделі: твої реальні фрази → що мало статися.

Запуск (гра закрита; Хомі краще вимкнути, щоб модель не мінялась у відеокарті):
    .venv\\Scripts\\python -m agent.eval_dialogs                       # модель з налаштувань
    .venv\\Scripts\\python -m agent.eval_dialogs --model qwen3.5:35b
    .venv\\Scripts\\python -m agent.eval_dialogs --only page           # лише перевірки, в id яких є «page»
    .venv\\Scripts\\python -m agent.eval_dialogs --reflex              # лише швидкі команди, без моделі (секунди)

Нічого справжнього не виконує: інструменти «удавані» — записують виклик і повертають правдоподібну відповідь.
Шлях фрази той самий, що в живій розмові: спершу router.route (швидкі команди), потім Brain.ask (Gemma).
Перевірки — evals\\cases.json; результат — таблиця тут і evals\\results\\<модель>-<час>.json.
"""
import json
import re
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

from .config import REPO_DIR, load_config
from .router import route
from .text import claims_action, claims_work_in_progress, is_noise, is_yes, looks_ukrainian, wants_other_language
from .tools import Tools

CASES = REPO_DIR / "evals" / "cases.json"
RESULTS = REPO_DIR / "evals" / "results"
PAGE = "тренування_ігоря"
# дії, після яких «зробила» — правда (інші інструменти лише щось дізнаються)
ACTION_TOOLS = {"open_app", "close_app", "media", "play_music", "open_website", "search_on_site", "open_page",
                "make_page", "edit_page", "set_reminder", "window", "click_on_screen", "open_folder", "remember", "forget_fact",
                "shutdown_timer", "cancel_shutdown", "sleep_pc", "lock_pc", "take_screenshot", "notes_add",
                "organize_downloads", "mark_game"}
CONFIRM = {"close_app", "shutdown_timer", "sleep_pc"}
PURE = {"current_datetime", "date_difference", "recall"}           # без побічних дій — справжні


def _host(url: str) -> str:
    return re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0] or "сайт"


class FakeTools(Tools):
    """Ті самі описи інструментів для моделі, але виклики лише записуються."""

    def __init__(self, cfg: dict, state: dict):
        super().__init__(cfg)
        self.calls: list[tuple[str, dict]] = []
        self.last_user_text = ""
        self.pending = None
        busy = PAGE if state.get("page_busy") else None
        names = [] if state.get("no_pages") else [PAGE]
        self._page_builder = types.SimpleNamespace(
            busy=busy, last=None, names=lambda: names,
            status=lambda: (f"Сторінка «{busy}»: пишу код, минуло 1:05, зараз 140 рядків." if busy else
                            "Зараз нічого не пишу." + (f" Готова сторінка «{names[0]}» — можу відкрити." if names else "")))
        self._task = ({"name": PAGE, "request": "трекер тренувань з календарем", "t": time.time() - 600}
                      if state.get("page_task") else None)
        self._overrides = dict(state.get("tool_results", {}))

    def last_page_task(self):
        return self._task

    def call(self, name: str, args: dict) -> str:
        args = dict(args or {})
        self.calls.append((name, args))
        if name in CONFIRM and not (args.get("confirmed") and is_yes(self.last_user_text)):
            self.awaiting = (name, {k: v for k, v in args.items() if k != "confirmed"})
            what = {"close_app": f"Закрити {args.get('name', 'програму')}? Незбережене може пропасти",
                    "shutdown_timer": "Точно вимкнути комп'ютер", "sleep_pc": "Перевести комп'ютер у сон"}[name]
            return (f"ПОТРІБНЕ ПІДТВЕРДЖЕННЯ. Нічого ще не зроблено. Коротко спитай користувача: «{what}?» "
                    "Якщо він скаже «так», виклич цей самий інструмент ще раз з confirmed=true.")
        self.awaiting = None
        if name in self._overrides:                     # що «повернув» інструмент саме в цій перевірці
            return self._overrides[name]
        if name in PURE:
            return super().call(name, args)
        a = args
        at = (datetime.now() + timedelta(minutes=float(a.get("minutes", 1) or 1))).strftime("%H:%M")
        canned = {
            "page_status": lambda: self._page_builder.status(),
            "open_page": lambda: (f"Відкрила сторінку «{self._page_builder.names()[0]}»." if self._page_builder.names()
                                  else "Сторінки з такою назвою немає. Жодної сторінки ще не створено."),
            "make_page": lambda: (f"Почала писати сторінку «{a.get('name', 'сторінка')}». Це займе хвилину-дві; "
                                  "коли буде готово — сама скажу й відкрию."),
            "edit_page": lambda: "Почала правити сторінку. Коли буде готово — сама скажу.",
            "open_app": lambda: f"Відкрила {a.get('name', 'програму')}.",
            "close_app": lambda: f"Закрила: {a.get('name', 'програму')}.",
            "media": lambda: {"pause": "Поставила на паузу.", "play": "Продовжила."}.get(a.get("action"), "Готово."),
            "play_music": lambda: f"Увімкнула музику: {a.get('query') or 'твої вподобані'}.",
            "web_search": lambda: (f"Результати пошуку «{a.get('query', '')}» (тестова заглушка): "
                                   "1. Довідкова стаття з загальним описом теми."),
            "search_on_site": lambda: f"Відкрила пошук «{a.get('query', '')}» на {a.get('site', 'сайті')}.",
            "open_website": lambda: f"Відкрила сайт {_host(a.get('url', ''))}.",
            "read_page": lambda: "Текст сторінки (тестова заглушка): коротка новина.",
            "wiki": lambda: "Вікіпедія (тестова заглушка): коротка довідка.",
            "set_reminder": lambda: f"Таймер поставлено: о {at} нагадаю — {a.get('text') or 'час вийшов'}.",
            "look_at_screen": lambda: "На екрані: браузер із відкритою сторінкою новин, кнопки «I agree» і «I do not agree».",
            "list_folder": lambda: (f"У Робочий стіл\\{a.get('name', 'папка')}: папок 0, файлів 3. Файли: "
                                    "World of Tanks EU.lnk, Counter-Strike 2.url, Path of Exile 2.url"),
            "open_folder": lambda: f"Відкрила папку {a.get('name', '')}.",
            "remember": lambda: "Записано в пам'ять.",
            "forget_fact": lambda: f"Забула: Ігор про себе: «Я люблю {a.get('query', '')}»",
            "window": lambda: f"Готово: {a.get('action', '')} {a.get('name', '')}.".replace("  ", " "),
            "click_on_screen": lambda: f"Натиснула «{a.get('text', '')}».",
            "shutdown_timer": lambda: f"Готово: комп'ютер вимкнеться через {a.get('minutes', 0)} хв.",
            "take_screenshot": lambda: "Зробила знімок екрана.",
            "find_file": lambda: "Знайшла файл: Документи\\план.txt",
        }
        fn = canned.get(name)
        return fn() if fn else f"Готово ({name})."


_ONES = ["нуль", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять", "десять", "одинадцять",
         "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять",
         "дев'ятнадцять"]
_TENS = {2: "двадцять", 3: "тридцять", 4: "сорок", 5: "п'ятдесят", 6: "шістдесят", 7: "сімдесят", 8: "вісімдесят",
         9: "дев'яносто"}


def words(n: int) -> str:
    """Число 0–999 словами (як його каже Хомі): 82 → «вісімдесят два»."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    hundreds = ["", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот", "вісімсот", "дев'ятсот"]
    return hundreds[n // 100] + ("" if n % 100 == 0 else " " + words(n % 100))


def number_alts(n: int) -> str:
    """Регулярка: число цифрами або словами («два»/«дві»)."""
    w = words(n)
    w = re.escape(w).replace("два", "дв[аі]").replace("один", "одн?[аоиі]н?")
    return rf"(?:\b{n}\b|{w})"


def expand(pattern: str) -> str:
    """Підставляє в очікування те, що залежить від часу запуску: {now} — поточна година й хвилина."""
    now = datetime.now()
    near = [now - timedelta(minutes=1), now, now + timedelta(minutes=1)]
    hm = "|".join(rf"(?:{number_alts(t.hour)}\W+(?:годин\w*\W+)?{number_alts(t.minute)}|{t:%H}:{t:%M}|{t.hour}:{t:%M})"
                  for t in near)
    ny = (datetime(now.year + 1, 1, 1).date() - now.date()).days
    return pattern.replace("{now}", f"(?:{hm})").replace("{days_to_new_year}", number_alts(ny))


def load_cases(only: str | None = None) -> list[dict]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    return [c for c in cases if not only or only in c["id"]]


def check(case: dict, routed: str, calls: list, answer: str, tools: FakeTools) -> list[str]:
    """Що пішло не так (порожній список — перевірку пройдено)."""
    e, problems = case.get("expect", {}), []
    names = [n for n, _ in calls]
    if e.get("route") and e["route"] != routed:
        problems.append(f"шлях {routed}, а мав бути {e['route']}")
    if e.get("tools_any") and not set(names) & set(e["tools_any"]):
        problems.append(f"не викликала жодного з {e['tools_any']}")
    if e.get("no_tools") and names:
        problems.append(f"викликала {names}, хоча не треба")
    for t in e.get("forbid_tools", []):
        if t in names:
            problems.append(f"заборонено {t}")
    if e.get("answer_has") and not re.search(expand(e["answer_has"]), answer, re.I):
        problems.append(f"у відповіді нема /{e['answer_has']}/")
    if e.get("answer_not") and re.search(expand(e["answer_not"]), answer, re.I):
        problems.append(f"у відповіді є /{e['answer_not']}/")
    did_action = any(n in ACTION_TOOLS and not str(r).startswith("ПОТРІБНЕ") for (n, _), r in zip(calls, tools.results))
    if not did_action and claims_action(answer):
        problems.append("каже, що зробила, але нічого не зроблено")
    if not tools._page_builder.busy and "make_page" not in names and claims_work_in_progress(answer):
        problems.append("каже, що пише/працює, але нічого не пишеться")
    own = re.sub(r"«[^»]*»", "", answer)              # назви кнопок і програм у лапках («I do not agree») — не її мова
    if (routed == "brain" and own.strip() and not looks_ukrainian(own)     # готові фрази коду не перевіряємо
            and not wants_other_language(case["say"])):
        problems.append("відповідь не українською")
    if not answer.strip():
        problems.append("порожня відповідь")
    return problems


def run_case(case: dict, cfg: dict, brain_cls, reflex_only: bool) -> dict:
    state = case.get("state", {})
    tools = FakeTools(cfg, state)
    tools.results = []
    orig_call = tools.call

    def call(name, args, _c=orig_call):
        r = _c(name, args)
        tools.results.append(r)
        return r
    tools.call = call
    awaiting = tuple(state["awaiting"]) if state.get("awaiting") else None
    tools.pending = (awaiting[0], None) if awaiting else None
    tools.last_user_text = case["say"]
    def make_brain():
        brain = brain_cls(cfg)
        brain.tools = tools
        brain._memories = lambda: []                  # без особистої пам'яті з Open WebUI — перевірки відтворювані
        brain.diary = types.SimpleNamespace(prompt_block=lambda: "")          # щоденник і уроки щодня інші —
        brain.lessons = types.SimpleNamespace(prompt_block=lambda: "")        # з ними результати не порівняти
        brain.history = [{"role": r, "content": t} for r, t in case.get("history", [])]
        brain.remember_in_background = False          # щоб перевірка бачила, що запам'ятала сама
        brain.last_turn = time.time()
        return brain

    def ask(text):
        try:
            return make_brain().ask(text)
        except Exception as ex:  # noqa: BLE001
            return f"ПОМИЛКА: {ex}"

    t0 = time.time()
    rt = None if is_noise(case["say"]) else route(case["say"], awaiting, tools.last_page_task(), None)
    if is_noise(case["say"]):                         # як у main: шум Хомі пропускає мовчки
        routed, answer = "ignored", "(шум — Хомі пропускає)"
    elif rt is not None:
        routed = "reflex"
        if rt.kind in ("tool", "confirm"):
            answer = tools.call(rt.tool, rt.args)
            # як у main: вміст папки чи щоденника коротко переказує модель
            if rt.summarize and not reflex_only and not answer.startswith(("Не знайшла", "У щоденнику нічого")):
                answer = ask(f"{case['say']}\n\n({rt.summarize})\n{answer}")
        elif rt.kind == "decline":
            answer = "Добре, не роблю."
        else:
            answer = {"selection": "(виділений текст переказує Gemma)"}.get(rt.kind, f"(швидка дія: {rt.kind})")
    elif reflex_only:
        return {"id": case["id"], "skipped": True}
    else:
        routed = "brain"
        answer = ask(case["say"])
    dt = time.time() - t0
    problems = check(case, routed, tools.calls, answer, tools)
    return {"id": case["id"], "say": case["say"], "route": routed, "tools": tools.calls, "answer": answer,
            "seconds": round(dt, 1), "ok": not problems, "problems": problems}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    cfg = load_config()
    if "--model" in args:
        cfg["ollama"]["model"] = args[args.index("--model") + 1]
    only = args[args.index("--only") + 1] if "--only" in args else None
    reflex_only = "--reflex" in args
    from .brain import Brain
    cases = load_cases(only)
    model = cfg["ollama"]["model"]
    if not reflex_only:
        import requests
        for attempt in range(3):          # прогрів: перший запит після зміни моделі у відеокарті інколи падає
            try:
                requests.post(f"{cfg['ollama']['url']}/api/generate", timeout=300,
                              json={"model": model, "prompt": "", "keep_alive": "15m"}).raise_for_status()
                break
            except requests.RequestException as ex:
                print(f"прогрів моделі, спроба {attempt + 1}: {str(ex)[:100]}", flush=True)
                time.sleep(5)
    print(f"Модель: {model} · перевірок: {len(cases)}{' · лише швидкі команди' if reflex_only else ''}\n", flush=True)
    results = []
    for c in cases:
        r = run_case(c, cfg, Brain, reflex_only)
        if r.get("skipped"):
            continue
        results.append(r)
        mark = "✔" if r["ok"] else "✘"
        tools_s = ", ".join(n for n, _ in r["tools"]) or "—"
        print(f"{mark} {r['id']:<28} [{r['route']:<6} {r['seconds']:>5.1f} с] інструменти: {tools_s}", flush=True)
        if not r["ok"]:
            print(f"     «{r['say']}» → «{r['answer'][:160]}»")
            for p in r["problems"]:
                print(f"     · {p}")
    ok = sum(r["ok"] for r in results)
    brain_t = [r["seconds"] for r in results if r["route"] == "brain"]
    print(f"\nПРОЙДЕНО {ok} з {len(results)} ({ok / max(1, len(results)):.0%})"
          + (f" · середній час відповіді Gemma {sum(brain_t) / len(brain_t):.1f} с" if brain_t else ""))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{model.replace(':', '-')}-{datetime.now():%Y%m%d-%H%M}.json"
    out.write_text(json.dumps({"model": model, "passed": ok, "total": len(results), "results": results},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Збережено: {out}")


if __name__ == "__main__":
    main()
