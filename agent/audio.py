"""Мікрофон, розпізнавання моменту мовлення (VAD) і відтворення звуку."""
import collections
import queue

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
        device = a.get("input_device") or None
        self.stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                        blocksize=FRAME_SAMPLES, device=device,
                                        callback=lambda data, *_: self.frames.put(bytes(data)))
        self.stream.start()

    def drain(self):
        """Викидає все, що мікрофон записав, поки Хомі говорила (щоб не слухати саму себе)."""
        while not self.frames.empty():
            self.frames.get_nowait()

    def listen(self, end_silence_ms: int, max_seconds: float, start_timeout_s: float | None = None,
               interrupt=None):
        """Чекає на мовлення й записує його до паузи.

        Повертає (int16-масив, тривалість мовлення в секундах), None — якщо за
        start_timeout_s ніхто нічого не сказав, або "interrupt" — якщо до початку
        мовлення спрацювала подія interrupt (клік по віджету).
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
                if interrupt is not None and interrupt.is_set():
                    interrupt.clear()
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

    @staticmethod
    def play(samples: np.ndarray, rate: int):
        sd.play(samples, rate)
        sd.wait()

    def beep(self, up: bool = True):
        """Короткий сигнал: угору — «слухаю», донизу — «закінчила слухати»."""
        tones = (660, 990) if up else (990, 660)
        t = np.linspace(0, 0.09, int(RATE * 0.09), endpoint=False)
        fade = np.minimum(1, np.minimum(t, t[::-1]) / 0.01)
        wave = np.concatenate([0.25 * np.sin(2 * np.pi * f * t) * fade for f in tones])
        self.play(wave.astype(np.float32), RATE)
        self.drain()
