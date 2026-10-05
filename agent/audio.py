"""Мікрофон, розпізнавання моменту мовлення (VAD) і відтворення звуку."""
import collections
import queue
import time

import numpy as np
import sounddevice as sd
import webrtcvad

RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000


class Audio:
    def __init__(self, cfg: dict):
        a = cfg.get("audio", {})
        self.vad = webrtcvad.Vad(int(a.get("vad_aggressiveness", 2)))
        self.frames: queue.Queue[bytes] = queue.Queue()
        self.mic_level = 0.0
        self._play_env = None            # (час старту, гучність по 50 мс) того, що зараз звучить
        device = a.get("input_device") or None
        self.stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                        blocksize=FRAME_SAMPLES, device=device,
                                        callback=self._on_audio)
        self.stream.start()

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
               interrupt=None):
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
        x = samples.astype(np.float32)
        if samples.dtype == np.int16:
            x /= 32768.0
        chunk = max(1, int(rate * 0.05))
        n = len(x) // chunk
        env = np.sqrt(np.mean(x[:n * chunk].reshape(n, chunk) ** 2, axis=1)) if n else np.zeros(0)
        peak = float(env.max()) if len(env) else 0.0
        self._play_env = (time.time(), env / peak if peak > 0 else env)
        sd.play(samples, rate)
        sd.wait()
        self._play_env = None

    def beep(self, up: bool = True):
        """Короткий сигнал: угору — «слухаю», донизу — «закінчила слухати»."""
        tones = (660, 990) if up else (990, 660)
        t = np.linspace(0, 0.09, int(RATE * 0.09), endpoint=False)
        fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)
        wave = np.concatenate([0.25 * np.sin(2 * np.pi * f * t) * fade for f in tones])
        self.play(wave.astype(np.float32), RATE)
        self.drain()
