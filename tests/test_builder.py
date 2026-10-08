from agent import builder


def test_extract_html():
    raw = "Ось код:\n```html\n<!DOCTYPE html><html><body>Привіт</body></html>\n```\nГотово."
    assert builder.extract_html(raw) == "<!DOCTYPE html><html><body>Привіт</body></html>"
    assert builder.extract_html("<html><p>обірвано") is None
    assert builder.slug("Мої тренування!") == "мої-тренування"


def test_make_page_in_background(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "pages_dir", lambda: tmp_path)
    monkeypatch.setattr(builder.webbrowser, "open", lambda url: None)
    b = builder.PageBuilder({"ollama": {"url": "http://x", "model": "m"}, "pages": {"review_rounds": 0}},
                            log=lambda *a: None)
    monkeypatch.setattr(b, "_write", lambda prompt: "<!DOCTYPE html><html>" + ("редаг" if "поточний" in prompt else "нова") + "</html>")
    said = []
    import threading
    ev = threading.Event()

    def done(text):
        said.append(text)
        ev.set()
    first = b.make("тренування", "трекер віджимань", done)
    assert "Почала писати" in first
    assert ev.wait(5) and "Готово" in said[-1]
    assert "нова" in (tmp_path / "тренування.html").read_text(encoding="utf-8")
    ev.clear()
    b.edit("більші кнопки", "", done)
    assert ev.wait(5)
    assert "редаг" in (tmp_path / "тренування.html").read_text(encoding="utf-8")
    assert (tmp_path / "тренування.bak.html").exists()


def test_streaming_progress(monkeypatch, tmp_path):
    import json
    b = builder.PageBuilder({"ollama": {"url": "http://x", "model": "m"}}, log=lambda *a: None)
    shown = []
    b.on_task = shown.append
    b.busy, b.started = "сайт", 0
    lines = [json.dumps({"message": {"content": c}}).encode() for c in ("<!DOCTYPE html>\n<html>\n", "<body>Привіт</body>\n")]
    lines.append(json.dumps({"message": {"content": "</html>"}, "done": True}).encode())

    class R:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_lines(self): return iter(lines)
    monkeypatch.setattr(builder.requests, "post", lambda *a, **k: R())
    html = b._write("x")
    assert html.startswith("<!DOCTYPE html>") and html.endswith("</html>")
    assert b.lines == 3 and shown and "пишу" in shown[0]
    assert "3 рядків" in b.status()
    b.busy = None
    assert b.status() == "Зараз нічого не пишу."


def test_review_fixes_then_stops_on_ok(monkeypatch):
    b = builder.PageBuilder({"ollama": {"url": "http://x", "model": "m"}}, log=lambda *a: None)
    answers = iter(["<!DOCTYPE html><html>виправлено</html>", "OK"])
    seen = []

    def write(prompt):
        seen.append(prompt)
        return builder.extract_html(next(answers))
    monkeypatch.setattr(b, "_write", write)
    monkeypatch.setattr(builder, "js_errors", lambda html: "")
    out = b.review("<!DOCTYPE html><html>чернетка</html>", "трекер", rounds=3)
    assert out == "<!DOCTYPE html><html>виправлено</html>"
    assert len(seen) == 2 and "чернетка" in seen[0] and "виправлено" in seen[1]


def test_gemini_writes_and_falls_back(monkeypatch):
    import json
    cfg = {"ollama": {"url": "http://x", "model": "m"}, "coder": {"gemini_key": "k"}}
    b = builder.PageBuilder(cfg, log=lambda *a: None)
    b.busy, b.started = "сайт", 0
    sent = {}
    events = ["data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": t}]}}]})
              for t in ("<!DOCTYPE html>\n<html>", "Gemini</html>")]

    class R:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self): pass
        def iter_lines(self, decode_unicode=False): return iter(events)

    def post(url, **k):
        sent["url"], sent["key"] = url, k["headers"]["x-goog-api-key"]
        return R()
    monkeypatch.setattr(builder.requests, "post", post)
    assert b._write("x") == "<!DOCTYPE html>\n<html>Gemini</html>"
    assert "generativelanguage.googleapis.com" in sent["url"] and sent["key"] == "k"

    def broken(url, **k):
        raise builder.requests.ConnectionError("немає інтернету")
    monkeypatch.setattr(builder.time, "sleep", lambda s: None)
    told = []
    b.notify = told.append
    monkeypatch.setattr(builder.requests, "post", broken)
    monkeypatch.setattr(b, "_write_local", lambda prompt: "<!DOCTYPE html><html>Gemma</html>")
    assert "Gemma" in b._write("x")                                  # без інтернету — пише сама
    assert told and "пишу сама" in told[0] and "зв'язку" in told[0]  # і чесно каже про це вголос
    assert "Gemini" in b.status()


def test_gemini_overloaded_retries_then_succeeds(monkeypatch):
    import json
    b = builder.PageBuilder({"ollama": {"url": "http://x", "model": "m"}, "coder": {"gemini_key": "k"}},
                            log=lambda *a: None)
    b.busy, b.started = "сайт", 0
    monkeypatch.setattr(builder.time, "sleep", lambda s: None)
    calls = []
    ok = ["data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "<!DOCTYPE html><html>ok</html>"}]}}]})]

    class R:
        def __init__(self, code): self.status_code = code
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def raise_for_status(self):
            if self.status_code != 200:
                resp = type("Resp", (), {"status_code": self.status_code})()
                raise builder.requests.HTTPError(response=resp)
        def iter_lines(self, decode_unicode=False): return iter(ok)

    def post(url, **k):
        calls.append(url)
        return R(503 if len(calls) < 3 else 200)                     # двічі «перевантажений», потім пише
    monkeypatch.setattr(builder.requests, "post", post)
    monkeypatch.setattr(b, "_write_local", lambda p: (_ for _ in ()).throw(AssertionError("не мала писати сама")))
    assert b._write("x") == "<!DOCTYPE html><html>ok</html>" and len(calls) == 3 and b.author == "Gemini"
