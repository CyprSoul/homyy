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


class Audio:
    def __init__(self, cfg: dict):
        a = cfg.get("audio", {})
        self.vad = webrtcvad.Vad(int(a.get("vad_aggressiveness", 2)))
        self.frames: queue.Queue[bytes] = queue.Queue()
        self.mic_level = 0.0
        self._play_env = None            # (час старту, гучність по 50 мс) того, що зараз звучить
        self._last_play_end = 0.0
        self._play_lock = threading.Lock()   # нагадування з таймера не перебиває мову посередині
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
        self.cut = threading.Event()         # «стоп» під час мови Хомі
        self._dither = (np.random.default_rng(0).standard_normal(OUT_RATE) * 1e-4).astype(np.float32)
        self._dither_pos = 0
        try:
            self.out_stream = sd.OutputStream(samplerate=OUT_RATE, channels=1, dtype="float32",
                                              device=a.get("output_device") or None,
                                              callback=self._on_output)
            self.out_stream.start()
        except Exception:
            self.out_stream = None           # не вийшло — граємо по-старому через sd.play

    def _on_output(self, outdata, frames, *_):
        with self._out_lock:
            n = min(frames, len(self._out))
            outdata[:n, 0] = self._out[:n]
            outdata[n:, 0] = 0.0
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
               interrupt=None, abort=None):
        """Чекає на мовлення й записує його до паузи.

        Повертає (int16-масив, тривалість мовлення в секундах), None — якщо за
        start_timeout_s ніхто нічого не сказав, або "interrupt" — якщо до початку
        мовлення interrupt() повернула True (клік по сфері, початок/кінець гри).
        """
        pre_roll = collections.deque(maxlen=10)            # 300 мс до початку мовлення
        start_frames_needed = 3                            # 90 мс мовлення = старт
        end_frames_needed = end_silence_ms // FRAME_MS
        waited = 0
        streak = 0
        recording: list[bytes] = []
        silence = 0
        speech_frames_total = 0

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
            else:
                silence += 1
            too_long = len(recording) * FRAME_MS / 1000 >= max_seconds
            if silence >= end_frames_needed or too_long:
                pcm = np.frombuffer(b"".join(recording), dtype=np.int16)
                return pcm, speech_frames_total * FRAME_MS / 1000

    def play(self, samples: np.ndarray, rate: int):
        # Після тиші звукова карта/навушники «прокидаються» і з'їдають перші ~200 мс —
        # тому перед першим звуком додаємо трохи тиші, і обрізається вже вона, а не слова.
        idle = time.time() - self._last_play_end
        lead = 0.25 if idle > 2 else 0.03
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
