"""«Жива сфера» Хомі: окремий процес із плавною (60 к/с) анімацією на Qt.

Сфера дихає, переливається всередині й тремтить у такт голосу: твого, коли Хомі слухає,
і її власного, коли вона говорить. Колір — стан. Клік — покликати, перетягнути — перенести,
правий клік — меню.
"""
import math
from pathlib import Path
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
    "search": ((245, 158, 11), 2.2, 0.05, "Шукаю…"),
    "speak":  ((34, 197, 94), 1.3, 0.05, ""),
    "error":  ((239, 68, 68), 0.8, 0.03, "Щось не так"),
    "paused": ((75, 78, 92), 0.2, 0.01, "Пауза · не слухаю"),
    "game":   ((148, 163, 184), 0.3, 0.0, ""),
}
W, H = 150, 168
R = 40            # радіус сфери


def _run(cmd_q: mp.Queue, evt_q: mp.Queue, position: str, style: str = "thinking", tint: bool = False):
    # Ctrl+C у вікні Хомі долітає й до процесу сфери і рве малювання посеред кадру
    # (звідси лавина «QPainter…»). Сферу закриває головний процес — тут Ctrl+C ігноруємо.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
    from PySide6.QtGui import (QColor, QFont, QPainter, QPainterPath, QPen,
                               QRadialGradient)
    from PySide6.QtWidgets import QApplication, QMenu, QWidget

    # Нова сфера з точок (thinking-orbs, як на schoolees.github.io/thinking-orbs) — через вбудований
    # браузер Qt. Немає модуля (PySide6-Addons) — малюємо стару сферу.
    WebView = None
    if style == "thinking":
        try:
            from PySide6.QtCore import QCoreApplication, QUrl
            from PySide6.QtWebEngineWidgets import QWebEngineView as WebView
            QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        except Exception:
            WebView = None
    WEB_PAGE = Path(__file__).resolve().parent / "orb_web" / "orb.html"

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
            self.web = None
            if WebView is not None and WEB_PAGE.exists():
                self.web = WebView(self)
                self.web.setGeometry(0, 0, W, H)
                self.web.page().setBackgroundColor(Qt.transparent)
                self.web.setAttribute(Qt.WA_TranslucentBackground)
                self.web.setContextMenuPolicy(Qt.NoContextMenu)
                url = QUrl.fromLocalFile(str(WEB_PAGE))
                if tint:
                    url.setQuery("tint=1")
                self.web.load(url)
                self._sent_state, self._sent_level, self._level_t = None, -1.0, 0.0
                # сторінка вантажиться не миттєво — коли готова, ще раз передаємо стан
                self.web.loadFinished.connect(lambda ok: setattr(self, "_sent_state", None))
                # прозорий шар зверху: клік / перетягування / меню — як і раніше
                orb = self

                class MouseLayer(QWidget):
                    def mousePressEvent(self, e): orb.mousePressEvent(e)
                    def mouseMoveEvent(self, e): orb.mouseMoveEvent(e)
                    def mouseReleaseEvent(self, e): orb.mouseReleaseEvent(e)
                    def contextMenuEvent(self, e): orb.contextMenuEvent(e)
                self.layer = MouseLayer(self)
                self.layer.setGeometry(0, 0, W, H)
                self.layer.raise_()

        def send_web(self):
            """Передає стан і гучність голосу в сферу з точок (не частіше 20 разів на секунду)."""
            if self.state != self._sent_state:
                self._sent_state = self.state
                self.web.page().runJavaScript(f"window.setHomyyState && setHomyyState('{self.state}')")
            now = time.perf_counter()
            if now - self._level_t > 0.05 and abs(self.level - self._sent_level) > 0.02:
                self._level_t, self._sent_level = now, self.level
                self.web.page().runJavaScript(f"window.setLevel && setLevel({self.level:.3f})")

        def set_game_look(self, game: bool):
            """У грі: напівпрозорий джойстик, кліки проходять крізь нього в гру, мало кадрів."""
            if game == getattr(self, "_game_look", False):
                return
            self._game_look = game
            self.setWindowOpacity(0.6 if game else 1.0)
            self.setWindowFlag(Qt.WindowTransparentForInput, game)
            self.timer.setInterval(100 if game else 16)
            self.show()
            if getattr(self, "layer", None) is not None:
                self.layer.setAttribute(Qt.WA_TransparentForMouseEvents, game)                       # після зміни прапорців вікно треба показати знову

        # ---- дані від голосової Хомі ----------------------------------
        def step(self):
            try:
                while True:
                    kind, value = cmd_q.get_nowait()
                    if kind == "state" and value in STATES:
                        self.set_game_look(value == "game")
                        self.state = value
                    elif kind == "level":
                        value = value if math.isfinite(value) else 0.0
                        self.level += (max(0.0, min(1.0, value)) - self.level) * 0.5
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
            self.phase = (self.phase + dt * self.speed * (1 + 2 * self.level)) % 10000.0
            if self.web is not None:
                self.send_web()
            elif self.isVisible():
                self.update()

        # ---- малювання ------------------------------------------------
        def paint_gamepad(self, p):
            """Ігровий режим: неоновий HUD-приціл у стилі сучасних шутерів.

            Сегментоване кільце повільно обертається, по центру дихає фіолетове «серце» Хомі.
            Лише тонкі лінії — майже нічого не закриває в грі.
            """
            cx, cy = W / 2, R + 30
            t = self.phase
            pulse = 0.5 + 0.5 * math.sin(t * 2.0)
            violet, cyan = QColor(167, 139, 250), QColor(34, 211, 238)

            def neon(draw, color, width):
                """Неон: широка прозора «аура» + тонка яскрава лінія."""
                for w_, a in ((width * 4.5, 40), (width * 2.2, 90), (width, 255)):
                    c = QColor(color)
                    c.setAlpha(a)
                    p.setPen(QPen(c, w_, Qt.SolidLine, Qt.RoundCap))
                    draw()

            p.setBrush(Qt.NoBrush)
            # зовнішнє кільце з 4 сегментів, повільно обертається
            r1 = 34
            rect1 = QRectF(cx - r1, cy - r1, 2 * r1, 2 * r1)
            spin = (t * 25) % 360
            for k in range(4):
                start = int((spin + k * 90 + 12) * 16)
                neon(lambda st=start: p.drawArc(rect1, st, 66 * 16), violet, 1.6)

            # внутрішнє тонке кільце обертається назустріч, бірюзове
            r2 = 22
            rect2 = QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2)
            spin2 = (-t * 40) % 360
            for k in range(3):
                start = int((spin2 + k * 120) * 16)
                neon(lambda st=start: p.drawArc(rect2, st, 70 * 16), cyan, 1.0)

            # риски прицілу
            for ang in (0, 90, 180, 270):
                a = math.radians(ang)
                x1, y1 = cx + 40 * math.cos(a), cy + 40 * math.sin(a)
                x2, y2 = cx + 47 * math.cos(a), cy + 47 * math.sin(a)
                neon(lambda x1=x1, y1=y1, x2=x2, y2=y2: p.drawLine(QPointF(x1, y1), QPointF(x2, y2)),
                     violet, 1.4)

            # серце Хомі
            p.setPen(Qt.NoPen)
            glow = QRadialGradient(QPointF(cx, cy), 12 + 5 * pulse)
            glow.setColorAt(0.0, QColor(167, 139, 250, int(170 + 70 * pulse)))
            glow.setColorAt(1.0, QColor(139, 92, 246, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), 12 + 5 * pulse, 12 + 5 * pulse)
            core = QRadialGradient(QPointF(cx - 1, cy - 1.2), 4.5)
            core.setColorAt(0.0, QColor(255, 255, 255))
            core.setColorAt(0.45, QColor(196, 181, 253))
            core.setColorAt(1.0, QColor(124, 58, 237))
            p.setBrush(core)
            p.drawEllipse(QPointF(cx, cy), 3.8, 3.8)

        def paintEvent(self, _):
            if self.web is not None:          # малює сфера з точок у вбудованому браузері
                return
            # Painter завжди закриваємо: інакше одна помилка малювання тягне за собою нескінченний
            # потік «QPainter::begin…» у консоль і гальмує весь ПК.
            p = QPainter(self)
            try:
                p.setRenderHint(QPainter.Antialiasing)
                if self.state == "game":
                    self.paint_gamepad(p)
                else:
                    self.paint_orb(p)
            except Exception:
                if not getattr(self, "_paint_error_logged", False):
                    self._paint_error_logged = True
                    import traceback
                    (Path(__file__).resolve().parent / "orb_error.log").write_text(
                        traceback.format_exc(), encoding="utf-8")
                self.phase, self.level = 0.0, 0.0       # скидаємо стан, що міг зламатися
            finally:
                p.end()

        def paint_orb(self, p):
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
            topic = menu.addAction("Нова тема (забути поточну розмову)")
            menu.addSeparator()
            journal = menu.addAction("Відкрити журнал")
            off = menu.addAction("Вимкнути Хомі")
            chosen = menu.exec(e.globalPos())
            if chosen == wake:
                evt_q.put("click")
            elif chosen == pause:
                evt_q.put("pause")
            elif chosen == topic:
                evt_q.put("newtopic")
            elif chosen == journal:
                evt_q.put("journal")
            elif chosen == off:
                evt_q.put("quit")
                QApplication.quit()

    # Попередження Qt — не в консоль (їх бувають тисячі на секунду), а перші 50 — у файл.
    from PySide6.QtCore import qInstallMessageHandler
    qt_log = {"n": 0}

    def _qt_messages(_mode, _ctx, msg):
        if qt_log["n"] < 50:
            qt_log["n"] += 1
            with open(Path(__file__).resolve().parent / "orb_error.log", "a", encoding="utf-8") as f:
                f.write(msg + "\n")
    qInstallMessageHandler(_qt_messages)

    app = QApplication([])
    from PySide6.QtGui import QIcon
    icon = Path(__file__).resolve().parent / "assets" / "homyy.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    orb = Orb()
    orb.show()
    app.exec()


class OrbClient:
    """Те, що бачить голосова Хомі: set_state / set_level / події кліку."""

    def __init__(self, position: str = "bottom-right", style: str = "thinking", tint: bool = False):
        ctx = mp.get_context("spawn")
        self.cmd_q, self.evt_q = ctx.Queue(), ctx.Queue()
        self.proc = ctx.Process(target=_run, args=(self.cmd_q, self.evt_q, position, style, tint), daemon=True)
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
