"""Мікрофон, розпізнавання моменту мовлення (VAD) і відтворення звуку."""
import collections
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import webrtcvad

RATE = 16000
FRAME_MS = 30
OUT_RATE = 48000                 # частота виходу звуку (усе перераховуємо в неї)
FRAME_SAMPLES = RATE * FRAME_MS // 1000


class DoubleTalk:
    """Чи говорить людина поверх голосу Хомі (коли звук іде з колонок, мікрофон чує й Хомі).

    Порівнюємо гучність мікрофона з гучністю того, що Хомі зараз грає. Луна з колонок має
    сталу частку; якщо мікрофон раптом у кілька разів гучніший за звичну луну ~0.3 с поспіль —
    це ти.
    """

    def __init__(self, factor: float = 4.0, frames_needed: int = 10, floor: float = 0.01):
        self.factor, self.frames_needed, self.floor = factor, frames_needed, floor
        self.reset()

    def reset(self):
        self.est: float | None = None      # звична частка луни: мікрофон / те, що граємо
        self.run = 0

    def update(self, mic_rms: float, ref_rms: float, speech: bool) -> bool:
        if ref_rms < 1e-3 or not speech:
            self.run = 0
            return False
        ratio = mic_rms / ref_rms
        if self.est is None:
            self.est = ratio
        # Звична луна — «нижня межа» частки: швидко вниз, повільно вгору. Так перший кадр із ТВОЇМ
        # голосом (у навушниках луни нема) не стає «нормою», і твоя мова поверх Хомі помітна.
        self.est = ratio if ratio < self.est else 0.98 * self.est + 0.02 * ratio
        if ratio > self.factor * self.est and mic_rms > self.floor:
            self.run += 1
        else:
            self.run = 0
        return self.run >= self.frames_needed


class Audio:
    def __init__(self, cfg: dict):
        a = cfg.get("audio", {})
        self.vad = webrtcvad.Vad(int(a.get("vad_aggressiveness", 2)))
        self.frames: queue.Queue[bytes] = queue.Queue()
        self.mic_level = 0.0
        self._play_env = None            # (час старту, гучність по 50 мс) того, що зараз звучить
        self._last_play_end = 0.0
        self._play_lock = threading.Lock()   # нагадування з таймера не перебиває мову посередині
        # перебивання голосом поверх Хомі (див. DoubleTalk)
        self.barge_armed = threading.Event()
        self.barged = threading.Event()
        self._dt = DoubleTalk()
        self._vad_cb = webrtcvad.Vad(2)
        self._ref_hist: collections.deque = collections.deque(maxlen=200)   # (час, гучність виходу)
        self._levels: collections.deque = collections.deque(maxlen=330)     # гучність мікрофона ~10 с
        self.cut = threading.Event()         # «стоп» під час мови Хомі
        device = a.get("input_device") or None
        self.stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                        blocksize=FRAME_SAMPLES, device=device,
                                        callback=self._on_audio)
        self.stream.start()
        # Вихід звуку тримаємо відкритим постійно (грає тишу): інакше навушники/звукова карта
        # «прокидаються» на початку кожної фрази й з'їдають перші склади («…чір добрий»).
        self._out = np.zeros(0, dtype=np.float32)
        self._out_lock = threading.Lock()
        self._out_empty = threading.Event()
        self._out_empty.set()
        db = a.get("keepalive_db", "off")      # з навушниками шум чути — за замовчуванням вимкнено
        level = 0.0 if str(db).lower() == "off" else 10 ** (float(db) / 20)
        self._dither = (np.random.default_rng(0).standard_normal(OUT_RATE) * level).astype(np.float32)
        self._dither_pos = 0
        try:
            self.out_stream = sd.OutputStream(samplerate=OUT_RATE, channels=1, dtype="float32",
                                              device=a.get("output_device") or None,
                                              callback=self._on_output)
        except Exception:
            self.out_stream = None           # не вийшло — граємо по-старому через sd.play
        # Вихід відкриваємо лише поки Хомі говорить (+ кілька секунд): у деяких навушниках
        # відкритий звук постійно шипить. keep_output_open = true — тримати завжди (для колонок).
        self._keep_open = bool(a.get("keep_output_open", False))
        self._idle_close_s = float(a.get("output_idle_close_s", 3))
        if self.out_stream is not None:
            if self._keep_open:
                self.out_stream.start()
            else:
                threading.Thread(target=self._close_when_idle, daemon=True).start()

    def _ensure_output(self):
        if self.out_stream is not None and not self.out_stream.active:
            self.out_stream.start()

    def _close_when_idle(self):
        while True:
            time.sleep(0.5)
            try:
                if (self.out_stream.active and self._out_empty.is_set() and not self._play_lock.locked()
                        and time.time() - self._last_play_end > self._idle_close_s):
                    self.out_stream.stop()
            except Exception:
                pass

    def _on_output(self, outdata, frames, *_):
        with self._out_lock:
            n = min(frames, len(self._out))
            outdata[:n, 0] = self._out[:n]
            outdata[n:, 0] = 0.0
            if n:
                self._ref_hist.append((time.time(), float(np.sqrt(np.mean(self._out[:n] ** 2)))))
            self._out = self._out[n:]
            if not len(self._out):
                self._out_empty.set()
        # Ледь чутний шум (−80 дБ) замість «цифрової тиші»: монітори з HDMI-звуком і частина
        # навушників вимикаються на абсолютній тиші й «прокидаються», з'їдаючи перші склади.
        i = self._dither_pos
        idx = (np.arange(frames) + i) % len(self._dither)
        outdata[:, 0] += self._dither[idx]
        self._dither_pos = (i + frames) % len(self._dither)

    def stop_playback(self):
        """Перебили: миттєво замовкнути й не грати решту речень."""
        self.cut.set()
        with self._out_lock:
            self._out = np.zeros(0, dtype=np.float32)
            self._out_empty.set()

    def _on_audio(self, data, *_):
        raw = bytes(data)
        self.frames.put(raw)
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        self.mic_level = float(np.sqrt(np.mean(x * x)) / 32768.0)
        self._levels.append(self.mic_level)
        if self.barge_armed.is_set() and len(raw) == FRAME_SAMPLES * 2:
            now = time.time()
            ref = max((r for t, r in list(self._ref_hist) if now - t < 0.3), default=0.0)
            try:
                speech = self._vad_cb.is_speech(raw, RATE)
            except Exception:
                speech = False
            if self._dt.update(self.mic_level, ref, speech):
                self.barge_armed.clear()
                self.barged.set()
                self.stop_playback()

    def noise_floor(self) -> float:
        """Звичайний рівень тиші в кімнаті (вентилятори, ПК) за останні ~10 с."""
        levels = sorted(self._levels)
        return levels[len(levels) // 5] if levels else 0.0

    def loud_enough(self, pcm, factor: float = 4.0, floor: float = 0.008) -> bool:
        """Чи це справжній голос біля мікрофона, а не шум/луна, з якої розпізнавач «вигадує» слова."""
        x = pcm.astype(np.float32) / 32768.0
        if not len(x):
            return False
        # гучність мовної частини: 70-й перцентиль по кадрах 30 мс (паузи не тягнуть униз)
        n = len(x) // FRAME_SAMPLES
        if n == 0:
            return False
        frames = np.sqrt(np.mean(x[:n * FRAME_SAMPLES].reshape(n, FRAME_SAMPLES) ** 2, axis=1))
        level = float(np.percentile(frames, 70))
        return level > max(floor, factor * self.noise_floor())

    def arm_barge_in(self, on: bool):
        """Під час відповіді Хомі: стежити, чи не заговорив ти поверх неї."""
        self.barged.clear()
        self._dt.reset()
        (self.barge_armed.set if on else self.barge_armed.clear)()

    def level(self) -> float:
        """Гучність 0..1 для «живої сфери»: голос Хомі, коли вона говорить, інакше мікрофон."""
        env = self._play_env
        if env:
            start, values = env
            i = int((time.time() - start) / 0.05)
            return float(values[i]) if i < len(values) else 0.0
        return min(1.0, self.mic_level * 8)

    def drain(self):
        """Викидає все, що мікрофон записав, поки Хомі говорила (щоб не слухати саму себе)."""
        while not self.frames.empty():
            self.frames.get_nowait()

    def listen(self, end_silence_ms: int, max_seconds: float, start_timeout_s: float | None = None,
               interrupt=None, abort=None, turn=None, max_silence_ms: int = 2500):
        """Чекає на мовлення й записує його до паузи.

        Повертає (int16-масив, тривалість мовлення в секундах), None — якщо за
        start_timeout_s ніхто нічого не сказав, або "interrupt" — якщо до початку
        мовлення interrupt() повернула True (клік по сфері, початок/кінець гри).

        turn(pcm) -> bool — «людина договорила?» (Smart Turn). Тоді після короткої тиші
        end_silence_ms питаємо модель: так — кінець; ні — слухаємо далі, аж до max_silence_ms тиші.
        """
        self.last_turn = None                              # (ймовірність, після скількох мс тиші) — для журналу
        pre_roll = collections.deque(maxlen=10)            # 300 мс до початку мовлення
        start_frames_needed = 3                            # 90 мс мовлення = старт
        end_frames_needed = end_silence_ms // FRAME_MS
        waited = 0
        streak = 0
        recording: list[bytes] = []
        silence = 0
        speech_frames_total = 0
        checked = False                                    # уже питали модель у цій паузі
        max_frames = max_silence_ms // FRAME_MS

        while True:
            frame = self.frames.get()
            if abort is not None and abort():        # ззовні попросили припинити слухати
                return None
            if len(frame) != FRAME_SAMPLES * 2:
                continue
            is_speech = self.vad.is_speech(frame, RATE)

            if not recording:
                if interrupt is not None and interrupt():
                    return "interrupt"
                waited += 1
                pre_roll.append(frame)
                streak = streak + 1 if is_speech else 0
                if streak >= start_frames_needed:
                    recording = list(pre_roll)
                    speech_frames_total = streak
                    silence = 0
                elif start_timeout_s is not None and waited * FRAME_MS / 1000 > start_timeout_s:
                    return None
                continue

            recording.append(frame)
            if is_speech:
                speech_frames_total += 1 + silence    # короткі паузи всередині слова теж рахуємо
                silence = 0
                checked = False
            else:
                silence += 1
            too_long = len(recording) * FRAME_MS / 1000 >= max_seconds
            done = too_long
            if turn is None:
                done = done or silence >= end_frames_needed
            elif silence >= max_frames:
                done = True                                # довго мовчить — точно договорив
            elif silence >= end_frames_needed and not checked:
                checked = True
                pcm = np.frombuffer(b"".join(recording), dtype=np.int16)
                done = bool(turn(pcm))
                self.last_turn = (getattr(turn, "last", None), silence * FRAME_MS)
            if done:
                pcm = np.frombuffer(b"".join(recording), dtype=np.int16)
                return pcm, speech_frames_total * FRAME_MS / 1000

    def play(self, samples: np.ndarray, rate: int):
        # Після тиші звукова карта/навушники «прокидаються» і з'їдають перші ~200 мс —
        # тому перед першим звуком додаємо трохи тиші, і обрізається вже вона, а не слова.
        idle = time.time() - self._last_play_end
        stream_off = self.out_stream is not None and not self.out_stream.active
        lead = 0.25 if idle > 2 or stream_off else 0.03
        samples = np.concatenate([np.zeros(int(rate * lead), dtype=samples.dtype), samples])
        x = samples.astype(np.float32)
        if samples.dtype == np.int16:
            x /= 32768.0
        chunk = max(1, int(rate * 0.05))
        n = len(x) // chunk
        env = np.sqrt(np.mean(x[:n * chunk].reshape(n, chunk) ** 2, axis=1)) if n else np.zeros(0)
        peak = float(env.max()) if len(env) else 0.0
        with self._play_lock:
            self._play_env = (time.time(), env / peak if peak > 0 else env)
            if self.out_stream is not None:
                self._ensure_output()
                y = np.interp(np.arange(int(len(x) * OUT_RATE / rate)) * rate / OUT_RATE,
                              np.arange(len(x)), x).astype(np.float32)
                with self._out_lock:
                    self._out = np.concatenate([self._out, y])
                    self._out_empty.clear()
                self._out_empty.wait(timeout=len(y) / OUT_RATE + 3)
                time.sleep(self.out_stream.latency)      # дограє те, що вже в буфері пристрою
            else:
                sd.play(samples, rate)
                sd.wait()
            self._play_env = None
            self._last_play_end = time.time()

    def beep(self, up: bool = True):
        """Короткий сигнал: угору — «слухаю», донизу — «закінчила слухати»."""
        tones = (660, 990) if up else (990, 660)
        t = np.linspace(0, 0.09, int(RATE * 0.09), endpoint=False)
        fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)
        wave = np.concatenate([0.25 * np.sin(2 * np.pi * f * t) * fade for f in tones])
        self.play(wave.astype(np.float32), RATE)
        self.drain()
