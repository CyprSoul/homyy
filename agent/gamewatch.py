"""Чи зараз гра: повноекранне вікно або процес зі списку (лише Windows)."""
import sys

DEFAULT_IGNORE = {"explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "vivaldi.exe",
                  "opera.exe", "brave.exe", "vlc.exe", "mpc-hc64.exe", "potplayermini64.exe",
                  "python.exe", "pythonw.exe", "powershell.exe", "windowsterminal.exe"}


def classify(exe: str, fullscreen: bool, games: set[str], ignore: set[str]) -> bool:
    """Гра — якщо процес у списку ігор, або вікно на весь екран і це не браузер/плеєр."""
    exe = exe.lower()
    if exe in games:
        return True
    return fullscreen and exe not in ignore


def foreground() -> tuple[str, bool]:
    """(назва процесу активного вікна, чи займає воно весь монітор)."""
    if sys.platform != "win32":
        return "", False
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", False

    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, cls, 64)
    if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd"):     # робочий стіл / панель задач
        return "explorer.exe", False

    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = kernel32.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            exe = buf.value.rsplit("\\", 1)[-1]
        kernel32.CloseHandle(h)

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    full = (rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom)
    return exe, full


def set_low_priority(low: bool):
    """Поки граєш, Хомі поступається процесором грі."""
    if sys.platform != "win32":
        return
    import ctypes
    BELOW_NORMAL, NORMAL = 0x4000, 0x20
    k = ctypes.windll.kernel32
    k.SetPriorityClass(k.GetCurrentProcess(), BELOW_NORMAL if low else NORMAL)
