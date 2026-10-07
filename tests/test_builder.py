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
