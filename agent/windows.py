"""Вікна й виділений текст — миттєво, без «роздумів» моделі (лише Windows).

Згорнути / розгорнути / перейти у вікно за назвою, згорнути все, взяти виділений текст.
"""
import sys
import time

# Як люди називають програми голосом → що шукати в назві вікна чи процесу
SYNONYMS = {
    "термінал": ["terminal", "powershell", "cmd", "командний рядок"],
    "консоль": ["terminal", "powershell", "cmd"],
    "браузер": ["chrome", "edge", "firefox", "opera", "brave", "vivaldi"],
    "хром": ["chrome"],
    "провідник": ["explorer", "провідник", "file explorer"],
    "папку": ["explorer", "провідник"],
    "музику": ["youtube music", "spotify"],
    "ютуб": ["youtube"],
    "діскорд": ["discord"],
    "дискорд": ["discord"],
    "телеграм": ["telegram"],
    "стім": ["steam"],
}


def _user32():
    import ctypes
    return ctypes.windll.user32


def list_windows() -> list[tuple[int, str, str]]:
    """Видимі вікна верхнього рівня: (hwnd, заголовок, процес)."""
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):     # 4 = GW_OWNER
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if h:
            size = wintypes.DWORD(260)
            path = ctypes.create_unicode_buffer(260)
            if kernel32.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size)):
                exe = path.value.rsplit("\\", 1)[-1]
            kernel32.CloseHandle(h)
        if exe.lower() not in ("pythonw.exe", "python.exe", "textinputhost.exe", "applicationframehost.exe"):
            out.append((int(hwnd), buf.value, exe))
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_window(spoken: str, windows=None):
    """Найкраще вікно для «термінал», «дискорд», «ютуб»… → (hwnd, заголовок) або None."""
    from .screen import app_similarity
    windows = list_windows() if windows is None else windows
    q = spoken.lower().strip()
    keys = SYNONYMS.get(q, []) + [q]
    best, score = None, 0.0
    for hwnd, title, exe in windows:
        hay = f"{title} {exe.removesuffix('.exe')}".lower()
        s = max((1.0 if k in hay else app_similarity(k, exe.removesuffix(".exe")) for k in keys), default=0)
        s = max(s, max((app_similarity(k, title) for k in keys), default=0) * 0.95)
        if s > score:
            best, score = (hwnd, title), s
    return best if score >= 0.8 else None


def window_action(action: str, spoken: str = "") -> str:
    if sys.platform != "win32":
        return "Керувати вікнами можу лише у Windows."
    user32 = _user32()
    if action == "minimize_all":
        user32.keybd_event(0x5B, 0, 0, 0)          # Win + D — показати робочий стіл
        user32.keybd_event(0x44, 0, 0, 0)
        user32.keybd_event(0x44, 0, 2, 0)
        user32.keybd_event(0x5B, 0, 2, 0)
        return "Згорнула все."
    found = find_window(spoken)
    if not found:
        titles = ", ".join(t for _, t, _ in list_windows()[:8])
        return f"Не бачу вікна «{spoken}». Відкриті: {titles}."
    hwnd, title = found
    if action == "minimize":
        user32.ShowWindow(hwnd, 6)
        return f"Згорнула «{title}»."
    if action == "maximize":
        user32.ShowWindow(hwnd, 3)
        user32.SetForegroundWindow(hwnd)
        return f"Розгорнула «{title}» на весь екран."
    # focus / restore: показати й перейти
    user32.ShowWindow(hwnd, 9)
    user32.keybd_event(0x12, 0, 0, 0)              # Alt — інакше Windows не дає перехопити фокус
    user32.SetForegroundWindow(hwnd)
    user32.keybd_event(0x12, 0, 2, 0)
    return f"Перейшла у «{title}»."


def selected_text() -> str:
    """Виділений текст в активному вікні: Ctrl+C → буфер обміну."""
    if sys.platform != "win32":
        return ""
    import ctypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    seq = user32.GetClipboardSequenceNumber()
    user32.keybd_event(0x11, 0, 0, 0)              # Ctrl + C
    user32.keybd_event(0x43, 0, 0, 0)
    user32.keybd_event(0x43, 0, 2, 0)
    user32.keybd_event(0x11, 0, 2, 0)
    for _ in range(20):                            # чекаємо, поки програма покладе текст у буфер
        time.sleep(0.05)
        if user32.GetClipboardSequenceNumber() != seq:
            break
    else:
        return ""
    text = ""
    if user32.OpenClipboard(None):
        try:
            h = user32.GetClipboardData(13)        # CF_UNICODETEXT
            if h:
                p = kernel32.GlobalLock(h)
                if p:
                    text = ctypes.wstring_at(p)
                    kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()
    return text.strip()
