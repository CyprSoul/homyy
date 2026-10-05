"""Telegram-бот Хомі: пиши текстом або надсилай голосові з будь-якого місця.

Працює в тому ж процесі, що й голосова Хомі (той самий характер, пам'ять, інструменти),
але з окремою історією розмови. Відповідає ЛИШЕ людям зі списку allowed_ids.
Поки ти граєш, повідомлення чекають і обробляються після гри, щоб не гальмувати її.
"""
import io
import threading
import time

import numpy as np
import requests

API = "https://api.telegram.org/bot{token}/{method}"
FILE = "https://api.telegram.org/file/bot{token}/{path}"


def resample_to_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate == 16000:
        return audio
    n = int(len(audio) * 16000 / rate)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)


def ogg_to_pcm16k(data: bytes) -> np.ndarray:
    """Голосове з Telegram (OGG/Opus) → int16, 16 кГц для Whisper."""
    import soundfile as sf
    audio, rate = sf.read(io.BytesIO(data), dtype="float32")
    return (np.clip(resample_to_16k(audio, rate), -1, 1) * 32767).astype(np.int16)


class TelegramBot:
    def __init__(self, cfg: dict, brain, stt, log, is_gaming):
        t = cfg.get("telegram", {})
        self.token = t.get("token", "")
        self.allowed = {int(x) for x in t.get("allowed_ids", [])}
        self.brain, self.stt, self.log, self.is_gaming = brain, stt, log, is_gaming
        self.offset = 0
        self.waiting: list[dict] = []

    def _call(self, method: str, **params):
        r = requests.post(API.format(token=self.token, method=method), json=params, timeout=40)
        r.raise_for_status()
        return r.json().get("result")

    def send(self, chat_id: int, text: str):
        for i in range(0, len(text), 4000):            # ліміт Telegram — 4096 символів
            self._call("sendMessage", chat_id=chat_id, text=text[i:i + 4000])

    def _voice_text(self, msg: dict) -> str:
        file_id = (msg.get("voice") or msg.get("audio"))["file_id"]
        path = self._call("getFile", file_id=file_id)["file_path"]
        data = requests.get(FILE.format(token=self.token, path=path), timeout=60).content
        return self.stt.command(ogg_to_pcm16k(data))

    def handle(self, msg: dict):
        chat_id, user_id = msg["chat"]["id"], msg.get("from", {}).get("id")
        if user_id not in self.allowed:
            self.log("telegram", f"чужий користувач {user_id} — ігнорую")
            self.send(chat_id, f"Я особиста помічниця й відповідаю лише господарю.\n"
                               f"Якщо це ти — додай свій ID {user_id} у config.toml → [telegram] allowed_ids.")
            return
        if self.is_gaming():
            self.waiting.append(msg)
            if len(self.waiting) == 1:
                self.send(chat_id, "🎮 Ти зараз граєш — щоб не гальмувати гру, відповім, щойно закінчиш.")
            return
        self._call("sendChatAction", chat_id=chat_id, action="typing")
        if "voice" in msg or "audio" in msg:
            text = self._voice_text(msg)
            if not text:
                self.send(chat_id, "Не розчула голосове 🙈 Спробуй ще раз.")
                return
            self.send(chat_id, f"🎙️ «{text}»")
        else:
            text = msg.get("text", "").strip()
        if not text or text == "/start":
            self.send(chat_id, "Привіт! Це Хомі 💜 Пиши мені або надсилай голосові.")
            return
        self.log("telegram", f"Ти: {text}")
        answer = self.brain.ask(text, on_tool=lambda n, a: self.log("інструмент", f"{n} {a}"))
        self.log("telegram", f"Хомі: {answer}")
        self.send(chat_id, answer or "…")

    def run(self):
        if not self.token:
            return
        self.log("✓", "Telegram-бот на зв'язку")
        while True:
            try:
                if self.waiting and not self.is_gaming():
                    pending, self.waiting = self.waiting, []
                    for m in pending:
                        self.handle(m)
                updates = self._call("getUpdates", offset=self.offset, timeout=25,
                                     allowed_updates=["message"]) or []
                for u in updates:
                    self.offset = u["update_id"] + 1
                    if "message" in u:
                        try:
                            self.handle(u["message"])
                        except Exception as e:
                            self.log("telegram помилка", str(e)[:200])
            except requests.RequestException as e:
                self.log("telegram", f"немає зв'язку ({str(e)[:80]}), пробую знову за 15 с")
                time.sleep(15)

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()
