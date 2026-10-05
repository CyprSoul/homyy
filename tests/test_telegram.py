import numpy as np

from agent.telegram_bot import TelegramBot, resample_to_16k


class FakeBrain:
    def ask(self, text, on_tool=None):
        return f"відповідь на: {text}"


def make_bot(gaming=False):
    bot = TelegramBot({"telegram": {"token": "t", "allowed_ids": [42]}}, FakeBrain(), None,
                      lambda *a: None, is_gaming=lambda: gaming)
    bot.sent = []
    bot._call = lambda method, **p: bot.sent.append((method, p)) if method != "getFile" else None
    return bot


def msg(user, text):
    return {"chat": {"id": user}, "from": {"id": user}, "text": text}


def test_only_owner_gets_answers():
    bot = make_bot()
    bot.handle(msg(7, "привіт"))
    assert "лише господарю" in bot.sent[-1][1]["text"] and "7" in bot.sent[-1][1]["text"]
    bot.handle(msg(42, "котра година"))
    assert bot.sent[-1] == ("sendMessage", {"chat_id": 42, "text": "відповідь на: котра година"})


def test_waits_while_gaming():
    bot = make_bot(gaming=True)
    bot.handle(msg(42, "a"))
    bot.handle(msg(42, "b"))
    assert len(bot.waiting) == 2 and sum(1 for m, _ in bot.sent if m == "sendMessage") == 1


def test_resample():
    assert len(resample_to_16k(np.zeros(48000, dtype=np.float32), 48000)) == 16000
