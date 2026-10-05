"""«Жива сфера» Хомі: окремий процес із плавною (60 к/с) анімацією на Qt.

Сфера дихає, переливається всередині й тремтить у такт голосу: твого, коли Хомі слухає,
і її власного, коли вона говорить. Колір — стан. Клік — покликати, перетягнути — перенести,
правий клік — меню.
"""
import math
import multiprocessing as mp
import queue
import time

# стан: (колір RGB, швидкість «життя», сила хвилястості, підпис)
STATES = {
    "boot":   ((120, 125, 140), 0.4, 0.02, "Прокидаюсь…"),
    "sleep":  ((139, 92, 246), 0.35, 0.025, ""),
    "listen": ((34, 211, 238), 1.0, 0.05, "Слухаю…"),
    "hear":   ((59, 130, 246), 1.6, 0.04, "Розбираю…"),
    "think":  ((245, 158, 11), 2.0, 0.045, "Думаю…"),
    "speak":  ((34, 197, 94), 1.3, 0.05, ""),
    "error":  ((239, 68, 68), 0.8, 0.03, "Щось не так"),
    "paused": ((75, 78, 92), 0.2, 0.01, "Пауза · не слухаю"),
}
W, H = 150, 168
R = 40            # радіус сфери


def _run(cmd_q: mp.Queue, evt_q: mp.Queue, position: str):
    from PySide6.QtCore import QPointF, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QRadialGradient
    from PySide6.QtWidgets import QApplication, QMenu, QWidget

    def qc(rgb, a=255, k=1.0, white=0.0):
        r, g, b = (min(255, int(c * k + (255 - c * k) * white)) for c in rgb)
        return QColor(r, g, b, int(a))

    class Orb(QWidget):
        def __init__(self):
            super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.resize(W, H)
            geo = QApplication.primaryScreen().availableGeometry()
            if position == "top-left":
                self.move(geo.left() + 16, geo.top() + 16)
            else:
                self.move(geo.right() - W - 16, geo.bottom() - H - 8)
            self.state = "boot"
            self.color = list(STATES["boot"][0])
            self.speed, self.wobble = STATES["boot"][1], STATES["boot"][2]
            self.level = 0.0
            self.phase = 0.0
            self.last = time.perf_counter()
            self.drag = None
            timer = QTimer(self)
            timer.timeout.connect(self.step)
            timer.start(16)

        # ---- дані від голосової Хомі ----------------------------------
        def step(self):
            try:
                while True:
                    kind, value = cmd_q.get_nowait()
                    if kind == "state" and value in STATES:
                        self.state = value
                    elif kind == "level":
                        self.level += (min(1.0, value) - self.level) * 0.5
                    elif kind == "quit":
                        QApplication.quit()
                        return
            except queue.Empty:
                pass
            now = time.perf_counter()
            dt, self.last = now - self.last, now
            target, speed, wobble, _ = STATES[self.state]
            k = min(1.0, dt * 4)                          # плавна зміна кольору й характеру
            self.color = [c + (t - c) * k for c, t in zip(self.color, target)]
            self.speed += (speed - self.speed) * k
            self.wobble += (wobble - self.wobble) * k
            self.level *= 0.92
            self.phase += dt * self.speed * (1 + 2 * self.level)
            self.update()

        # ---- малювання ------------------------------------------------
        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            t, lvl, col = self.phase, self.level, self.color
            cx, cy = W / 2, R + 30
            breath = 0.5 + 0.5 * math.sin(t * 1.3)

            # сяйво навколо
            gr = R * (1.55 + 0.12 * breath + 0.5 * lvl)
            glow = QRadialGradient(QPointF(cx, cy), gr)
            glow.setColorAt(0.0, qc(col, 150))
            glow.setColorAt(0.45, qc(col, 60))
            glow.setColorAt(1.0, qc(col, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), gr, gr)

            # жива поверхня: радіус хвилюється сумою синусоїд
            path = QPainterPath()
            amp = self.wobble + 0.12 * lvl
            r0 = R * (0.94 + 0.05 * breath + 0.12 * lvl)
            for i in range(97):
                a = i / 96 * 2 * math.pi
                r = r0 * (1 + amp * (math.sin(3 * a + t * 1.7) * 0.6
                                     + math.sin(5 * a - t * 2.3) * 0.3
                                     + math.sin(2 * a + t * 0.9) * 0.4))
                pt = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            body = QRadialGradient(QPointF(cx - R * 0.35, cy - R * 0.4), R * 1.5)
            body.setColorAt(0.0, qc(col, 255, white=0.65))
            body.setColorAt(0.35, qc(col, 245))
            body.setColorAt(1.0, qc(col, 235, k=0.35))
            p.setBrush(body)
            p.drawPath(path)

            # переливи всередині
            p.setClipPath(path)
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            for j in range(3):
                a = t * (0.8 + 0.35 * j) + j * 2.1
                bx, by = cx + R * 0.38 * math.cos(a), cy + R * 0.3 * math.sin(a * 1.3)
                br = R * (0.55 + 0.1 * math.sin(t + j))
                g = QRadialGradient(QPointF(bx, by), br)
                g.setColorAt(0.0, qc(col, 90, white=0.4))
                g.setColorAt(1.0, qc(col, 0))
                p.setBrush(g)
                p.drawEllipse(QPointF(bx, by), br, br)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setClipping(False)

            # блік
            hl = QRadialGradient(QPointF(cx - R * 0.32, cy - R * 0.42), R * 0.45)
            hl.setColorAt(0.0, QColor(255, 255, 255, 170))
            hl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(hl)
            p.drawEllipse(QPointF(cx - R * 0.32, cy - R * 0.42), R * 0.45, R * 0.45)

            # підпис
            caption = STATES[self.state][3]
            if caption:
                p.setFont(QFont("Segoe UI", 9, QFont.Bold))
                rect = self.rect().adjusted(0, int(cy + R + 14), 0, 0)
                p.setPen(QColor(0, 0, 0, 200))
                p.drawText(rect.translated(1, 1), Qt.AlignHCenter | Qt.AlignTop, caption)
                p.setPen(QColor(245, 245, 250))
                p.drawText(rect, Qt.AlignHCenter | Qt.AlignTop, caption)

        # ---- миша -----------------------------------------------------
        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self.drag = (e.globalPosition().toPoint(), self.pos(), False)

        def mouseMoveEvent(self, e):
            if self.drag:
                start, origin, _ = self.drag
                delta = e.globalPosition().toPoint() - start
                if delta.manhattanLength() > 3:
                    self.drag = (start, origin, True)
                    self.move(origin + delta)

        def mouseReleaseEvent(self, e):
            if e.button() == Qt.LeftButton and self.drag and not self.drag[2]:
                evt_q.put("click")
            self.drag = None

        def contextMenuEvent(self, e):
            menu = QMenu(self)
            wake = menu.addAction("Покликати Хомі")
            pause = menu.addAction("Продовжити слухати" if self.state == "paused" else "Пауза (не слухати)")
            menu.addSeparator()
            off = menu.addAction("Вимкнути Хомі")
            chosen = menu.exec(e.globalPos())
            if chosen == wake:
                evt_q.put("click")
            elif chosen == pause:
                evt_q.put("pause")
            elif chosen == off:
                evt_q.put("quit")
                QApplication.quit()

    app = QApplication([])
    orb = Orb()
    orb.show()
    app.exec()


class OrbClient:
    """Те, що бачить голосова Хомі: set_state / set_level / події кліку."""

    def __init__(self, position: str = "bottom-right"):
        ctx = mp.get_context("spawn")
        self.cmd_q, self.evt_q = ctx.Queue(), ctx.Queue()
        self.proc = ctx.Process(target=_run, args=(self.cmd_q, self.evt_q, position), daemon=True)
        self.proc.start()

    def set_state(self, state: str):
        self.cmd_q.put(("state", state))

    def set_level(self, level: float):
        self.cmd_q.put(("level", float(level)))

    def next_event(self, timeout: float):
        try:
            return self.evt_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def alive(self) -> bool:
        return self.proc.is_alive()
