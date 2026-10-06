"""Натиснути на екрані на напис: знімок → вбудоване в Windows розпізнавання тексту (OCR) → клік.

Усе локально: знімок нікуди не йде з ПК. Працює з будь-якими програмами (Steam, браузер, ігрові лаунчери),
бо шукає текст на картинці, а не всередині програми.
"""
import asyncio
import io
import re
import sys
from difflib import SequenceMatcher

_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie", "ж": "zh", "з": "z",
    "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ь": "", "ю": "iu", "я": "ia", "'": "", "’": "", "ы": "y", "э": "e", "ё": "e", "ъ": "",
})


def norm(text: str) -> str:
    """Для порівняння: нижній регістр, латиницею, лише букви й цифри («Ігорку 2018» → «ihorku2018»)."""
    t = text.lower().translate(_TRANSLIT)
    t = t.replace("kh", "h").replace("ih", "ig")      # «Ігор» вимовляють і пишуть як «Igor»
    return re.sub(r"[^a-z0-9]", "", t)


def similarity(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) >= 4 and (a in b or b in a):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def app_similarity(spoken: str, name: str) -> float:
    """Назва програми на слух («дискорд», «стім», «телеграм») проти справжньої («Discord», «Steam»,
    «Telegram Desktop»): латиницею й «за звучанням» (y=i, h=g, c=k…)."""
    def phon(t: str) -> str:
        t = norm(t)
        for a, b in (("ph", "f"), ("ea", "i"), ("ee", "i"), ("x", "ks"), ("q", "k"),
                     ("c", "k"), ("y", "i"), ("h", "g"), ("w", "v")):
            t = t.replace(a, b)
        return t
    a, b = phon(spoken), phon(name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # англійські назви кирилицею: «Геймс» → Games, «Стім» → Steam — збігаються «кістяком» приголосних
    skel = lambda t: re.sub(r"[aeiouy]", "", t)
    if len(skel(a)) >= 3 and skel(a) == skel(b):
        return 0.88
    if len(a) >= 4 and a in b:
        return 0.9
    if len(a) >= 3 and any(phon(w).startswith(a) for w in name.split()):
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def best_match(target: str, words: list[tuple[str, tuple[float, float, float, float]]]):
    """words — (текст, (x, y, ширина, висота)) у порядку читання. Шукаємо слово або 2–4 сусідні слова,
    найбільше схожі на target. Повертає (текст, центр (x, y), схожість) або None."""
    best = None
    for i in range(len(words)):
        x0, y0, _, _ = words[i][1]
        x1 = y1 = 0.0
        texts = []
        for j in range(i, min(i + 4, len(words))):
            text, (x, y, w, h) = words[j]
            if abs(y - y0) > max(h, 10):       # лише в межах одного рядка
                break
            texts.append(text)
            x1, y1 = max(x1, x + w), max(y1, y + h)
            score = similarity(target, " ".join(texts))
            if best is None or score > best[2]:
                best = (" ".join(texts), ((x0 + x1) / 2, (y0 + y1) / 2), score)
    return best


async def _ocr_words(png: bytes):
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png)
    await writer.store_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:                     # мовний пакет OCR для мови Windows не встановлено — беремо англійську
        from winrt.windows.globalization import Language
        engine = OcrEngine.try_create_from_language(Language("en-US"))
    if engine is None:
        return []
    result = await engine.recognize_async(bitmap)
    words = []
    for line in result.lines:
        for w in line.words:
            r = w.bounding_rect
            words.append((w.text, (r.x, r.y, r.width, r.height)))
    return words


def screen_words():
    """Знімок основного екрана й усі слова на ньому з координатами (у пікселях екрана)."""
    import ctypes
    from PIL import ImageGrab
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)       # справжні пікселі, а не «масштабовані»
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    img = ImageGrab.grab(all_screens=False)
    scale = 1.0
    if max(img.size) > 2600:          # OCR Windows приймає до ~10000 px, але великі знімки повільні
        scale = 2600 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    words = asyncio.run(_ocr_words(buf.getvalue()))
    return [(t, (x / scale, y / scale, w / scale, h / scale)) for t, (x, y, w, h) in words]


def click(x: float, y: float):
    import ctypes
    u = ctypes.windll.user32
    u.SetCursorPos(int(x), int(y))
    u.mouse_event(0x0002, 0, 0, 0, 0)     # ліва кнопка вниз
    u.mouse_event(0x0004, 0, 0, 0, 0)     # і вгору


def available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winrt.windows.media.ocr  # noqa: F401
        return True
    except Exception:
        return False
