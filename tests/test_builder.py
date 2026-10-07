from agent import builder


def test_extract_html():
    raw = "Ось код:\n```html\n<!DOCTYPE html><html><body>Привіт</body></html>\n```\nГотово."
    assert builder.extract_html(raw) == "<!DOCTYPE html><html><body>Привіт</body></html>"
    assert builder.extract_html("<html><p>обірвано") is None
    assert builder.slug("Мої тренування!") == "мої-тренування"


def test_make_page_in_background(monkeypatch, tmp_path):
    monkeypatch.setattr(builder, "pages_dir", lambda: tmp_path)
    monkeypatch.setattr(builder.webbrowser, "open", lambda url: None)
    b = builder.PageBuilder({"ollama": {"url": "http://x", "model": "m"}}, log=lambda *a: None)
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
