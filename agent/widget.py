"""Віджет присутності: кулька в кутку екрана, що «дихає» й змінює колір за станом Хомі.

Клік — покликати Хомі без голосу. Перетягування — перенести. Правий клік — меню.
"""
import math
import queue
import time
import tkinter as tk

# стан: (колір, період «дихання» в секундах, підпис)
STATES = {
    "boot":   ("#6b7280", 3.0, "Прокидаюсь…"),
    "sleep":  ("#8b5cf6", 4.0, "«Хооміі»"),
    "listen": ("#22d3ee", 1.2, "Слухаю…"),
    "hear":   ("#3b82f6", 0.8, "Розбираю…"),
    "think":  ("#f59e0b", 0.7, "Думаю…"),
    "speak":  ("#22c55e", 0.45, "Говорю…"),
    "error":  ("#ef4444", 1.0, "Щось не так"),
}
KEY = "#010203"   # колір, який Windows робить прозорим


def _mix(color: str, k: float) -> str:
    """Темніший відтінок кольору: k=1 — сам колір, k=0 — чорний."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(4, int(c * k)) for c in (r, g, b))


class Widget:
    SIZE = 84

    def __init__(self, on_click, on_quit, position: str = "bottom-right"):
        self.on_click, self.on_quit = on_click, on_quit
        self.events: queue.Queue[str] = queue.Queue()
        self.state = "boot"
        self.t0 = time.time()

        root = self.root = tk.Tk()
        root.title("Хомі")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=KEY)
        try:
            root.wm_attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass

        w, h = self.SIZE, self.SIZE + 20
        c = self.canvas = tk.Canvas(root, width=w, height=h, bg=KEY, highlightthickness=0)
        c.pack()
        self.glow = c.create_oval(0, 0, 0, 0, outline="")
        self.core = c.create_oval(0, 0, 0, 0, outline="")
        self.arc = c.create_arc(6, 6, w - 6, w - 6, style="arc", width=3, outline="", start=0, extent=80)
        self.shadow = c.create_text(w / 2 + 1, h - 9, text="", fill="#000000", font=("Segoe UI", 9, "bold"))
        self.label = c.create_text(w / 2, h - 10, text="", fill="#f3f4f6", font=("Segoe UI", 9, "bold"))

        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = (sw - w - 24, sh - h - 70) if position == "bottom-right" else (24, 24)
        root.geometry(f"{w}x{h}+{x}+{y}")

        menu = self.menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Покликати Хомі", command=self.on_click)
        menu.add_separator()
        menu.add_command(label="Вимкнути Хомі", command=self.quit)

        self._press = None
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)
        c.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))
        self._tick()

    # ---- потокобезпечне керування ---------------------------------------
    def set_state(self, state: str):
        self.events.put(state)

    def quit(self):
        self.root.destroy()
        self.on_quit()

    def mainloop(self):
        self.root.mainloop()

    # ---- миша -----------------------------------------------------------
    def _on_press(self, e):
        self._press = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def _on_drag(self, e):
        if not self._press:
            return
        x0, y0, wx, wy, _ = self._press
        dx, dy = e.x_root - x0, e.y_root - y0
        if abs(dx) + abs(dy) > 3:
            self._press = (x0, y0, wx, wy, True)
            self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _on_release(self, _e):
        if self._press and not self._press[4]:
            self.on_click()
        self._press = None

    # ---- анімація -------------------------------------------------------
    def _tick(self):
        while not self.events.empty():
            self.state = self.events.get_nowait()
            self.t0 = time.time()
        color, period, text = STATES.get(self.state, STATES["error"])
        phase = (math.sin((time.time() - self.t0) * 2 * math.pi / period) + 1) / 2   # 0..1

        s, mid = self.SIZE, self.SIZE / 2
        r_core = s * (0.26 + 0.04 * phase)
        r_glow = s * (0.36 + 0.10 * phase)
        c = self.canvas
        c.coords(self.glow, mid - r_glow, mid - r_glow, mid + r_glow, mid + r_glow)
        c.itemconfig(self.glow, fill=_mix(color, 0.25 + 0.2 * phase))
        c.coords(self.core, mid - r_core, mid - r_core, mid + r_core, mid + r_core)
        c.itemconfig(self.core, fill=_mix(color, 0.75 + 0.25 * phase))

        if self.state in ("think", "hear"):
            c.itemconfig(self.arc, outline=color, start=(time.time() * 360) % 360)
        else:
            c.itemconfig(self.arc, outline="")
        c.itemconfig(self.label, text=text)
        c.itemconfig(self.shadow, text=text)
        self.root.after(40, self._tick)
