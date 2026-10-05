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
    "game":   ((148, 163, 184), 0.3, 0.0, ""),
}
W, H = 150, 168
R = 40            # радіус сфери


def _run(cmd_q: mp.Queue, evt_q: mp.Queue, position: str):
    from PySide6.QtCore import QPointF, Qt, QTimer
    from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                               QRadialGradient)
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
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.step)
            self.timer.start(16)

        def set_game_look(self, game: bool):
            """У грі: напівпрозорий джойстик, кліки проходять крізь нього в гру, мало кадрів."""
            if game == getattr(self, "_game_look", False):
                return
            self._game_look = game
            self.setWindowOpacity(0.55 if game else 1.0)
            self.setWindowFlag(Qt.WindowTransparentForInput, game)
            self.timer.setInterval(200 if game else 16)
            self.show()                       # після зміни прапорців вікно треба показати знову

        # ---- дані від голосової Хомі ----------------------------------
        def step(self):
            try:
                while True:
                    kind, value = cmd_q.get_nowait()
                    if kind == "state" and value in STATES:
                        self.set_game_look(value == "game")
                        self.state = value
                    elif kind == "level":
                        self.level += (min(1.0, value) - self.level) * 0.5
                    elif kind == "visible":           # під час гри сфера ховається й не малює
                        if value:
                            self.show()
                            self.timer.setInterval(16)
                        else:
                            self.hide()
                            self.timer.setInterval(400)
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
            if self.isVisible():
                self.update()

        # ---- малювання ------------------------------------------------
        def paint_gamepad(self, p):
            """Об'ємний глянцевий джойстик із фіолетовим «серцем» Хомі, що повільно дихає."""
            cx, cy = W / 2, R + 30
            pulse = 0.5 + 0.5 * math.sin(self.phase * 2.0)

            # тінь під джойстиком
            sh = QRadialGradient(QPointF(cx, cy + 30), 46)
            sh.setColorAt(0.0, QColor(0, 0, 0, 120))
            sh.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(sh)
            p.drawEllipse(QPointF(cx, cy + 30), 46, 9)

            # корпус
            body = QPainterPath()
            body.moveTo(cx - 30, cy - 20)
            body.cubicTo(cx - 10, cy - 24, cx + 10, cy - 24, cx + 30, cy - 20)
            body.cubicTo(cx + 44, cy - 20, cx + 47, cy - 8, cx + 45, cy + 6)
            body.cubicTo(cx + 43, cy + 22, cx + 37, cy + 29, cx + 28, cy + 27)
            body.cubicTo(cx + 20, cy + 25, cx + 16, cy + 13, cx + 10, cy + 11)
            body.lineTo(cx - 10, cy + 11)
            body.cubicTo(cx - 16, cy + 13, cx - 20, cy + 25, cx - 28, cy + 27)
            body.cubicTo(cx - 37, cy + 29, cx - 43, cy + 22, cx - 45, cy + 6)
            body.cubicTo(cx - 47, cy - 8, cx - 44, cy - 20, cx - 30, cy - 20)
            fill = QLinearGradient(QPointF(cx, cy - 24), QPointF(cx, cy + 29))
            fill.setColorAt(0.0, QColor(92, 99, 120))
            fill.setColorAt(0.35, QColor(48, 52, 66))
            fill.setColorAt(1.0, QColor(18, 20, 27))
            p.setBrush(fill)
            p.drawPath(body)

            # глянцевий відблиск зверху
            p.save()
            p.setClipPath(body)
            gl = QLinearGradient(QPointF(cx, cy - 24), QPointF(cx, cy - 4))
            gl.setColorAt(0.0, QColor(255, 255, 255, 90))
            gl.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(gl)
            p.drawEllipse(QPointF(cx, cy - 18), 40, 12)
            p.restore()

            # обвідка-кант
            rim = QLinearGradient(QPointF(cx, cy - 24), QPointF(cx, cy + 29))
            rim.setColorAt(0.0, QColor(200, 205, 225, 160))
            rim.setColorAt(1.0, QColor(0, 0, 0, 160))
            p.setPen(QPen(QBrush(rim), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPath(body)
            p.setPen(Qt.NoPen)

            def stick(x, y, r):
                well = QRadialGradient(QPointF(x, y), r + 2.5)
                well.setColorAt(0.6, QColor(8, 9, 12))
                well.setColorAt(1.0, QColor(8, 9, 12, 0))
                p.setBrush(well)
                p.drawEllipse(QPointF(x, y), r + 2.5, r + 2.5)
                cap = QRadialGradient(QPointF(x - r * 0.35, y - r * 0.4), r * 1.4)
                cap.setColorAt(0.0, QColor(130, 137, 158))
                cap.setColorAt(0.5, QColor(52, 56, 70))
                cap.setColorAt(1.0, QColor(22, 24, 31))
                p.setBrush(cap)
                p.drawEllipse(QPointF(x, y), r, r)

            stick(cx - 25, cy - 6, 6.5)          # лівий стік
            stick(cx + 12, cy + 4, 5.8)          # правий стік

            # хрестовина
            dx, dy = cx - 12, cy + 4
            cross = QPainterPath()
            cross.addRoundedRect(dx - 7, dy - 2.4, 14, 4.8, 1.5, 1.5)
            cross.addRoundedRect(dx - 2.4, dy - 7, 4.8, 14, 1.5, 1.5)
            cg = QLinearGradient(QPointF(dx, dy - 7), QPointF(dx, dy + 7))
            cg.setColorAt(0.0, QColor(96, 102, 122))
            cg.setColorAt(1.0, QColor(26, 28, 36))
            p.setBrush(cg)
            p.drawPath(cross.simplified())

            # кнопки A B X Y
            bx, by = cx + 26, cy - 6
            for ox, oy, col in ((0, 5.5, (34, 197, 94)), (5.5, 0, (239, 68, 68)),
                                (-5.5, 0, (59, 130, 246)), (0, -5.5, (245, 158, 11))):
                x, y = bx + ox, by + oy
                g = QRadialGradient(QPointF(x - 1, y - 1.2), 4.2)
                g.setColorAt(0.0, QColor(255, 255, 255, 230))
                g.setColorAt(0.35, QColor(*col))
                g.setColorAt(1.0, QColor(int(col[0] * 0.4), int(col[1] * 0.4), int(col[2] * 0.4)))
                p.setBrush(g)
                p.drawEllipse(QPointF(x, y), 3.1, 3.1)

            # фіолетове «серце» Хомі по центру
            hx, hy = cx, cy - 10
            glow = QRadialGradient(QPointF(hx, hy), 10 + 4 * pulse)
            glow.setColorAt(0.0, QColor(167, 139, 250, int(150 + 80 * pulse)))
            glow.setColorAt(1.0, QColor(139, 92, 246, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(hx, hy), 10 + 4 * pulse, 10 + 4 * pulse)
            core = QRadialGradient(QPointF(hx - 1, hy - 1.2), 4)
            core.setColorAt(0.0, QColor(255, 255, 255))
            core.setColorAt(0.4, QColor(196, 181, 253))
            core.setColorAt(1.0, QColor(124, 58, 237))
            p.setBrush(core)
            p.drawEllipse(QPointF(hx, hy), 3.4, 3.4)

        def paintEvent(self, _):
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            if self.state == "game":
                self.paint_gamepad(p)
                return
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

    def set_visible(self, visible: bool):
        self.cmd_q.put(("visible", bool(visible)))

    def next_event(self, timeout: float):
        try:
            return self.evt_q.get(timeout=timeout)
        except queue.Empty:
            return None

    def alive(self) -> bool:
        return self.proc.is_alive()
