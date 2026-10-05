"""Особисті сервіси, лише читання: Monobank (витрати, баланс) і Gmail (нові листи).

Ключі зберігаються тільки в agent\\config.toml на твоєму ПК.
"""
import email
import imaplib
import time
from email.header import decode_header, make_header

import requests

# Найпоширеніші коди категорій покупок (MCC) → зрозумілі назви.
MCC = {
    range(5411, 5412): "продукти", range(5499, 5500): "продукти", range(5811, 5815): "кафе й ресторани",
    range(5541, 5543): "пальне", range(4111, 4122): "транспорт", range(4131, 4132): "транспорт",
    range(5912, 5913): "аптеки", range(5814, 5815): "фастфуд", range(5815, 5819): "цифрові сервіси й ігри",
    range(4814, 4817): "зв'язок та інтернет", range(5651, 5700): "одяг", range(5732, 5735): "техніка",
    range(4900, 4901): "комунальні", range(7832, 7833): "кіно", range(5945, 5946): "іграшки й ігри",
    range(5310, 5312): "магазини", range(6010, 6013): "готівка й перекази", range(4829, 4830): "перекази",
}


def mcc_name(code: int) -> str:
    for r, name in MCC.items():
        if code in r:
            return name
    return "інше"


def spending_summary(items: list[dict]) -> dict:
    """Виписка Monobank → витрати за категоріями (суми в гривнях)."""
    total, cats = 0.0, {}
    for it in items:
        amount = it.get("amount", 0) / 100
        if amount >= 0:
            continue
        total += -amount
        name = mcc_name(int(it.get("mcc", 0)))
        cats[name] = cats.get(name, 0) + -amount
    top = sorted(cats.items(), key=lambda kv: -kv[1])[:6]
    return {"total": round(total, 2), "top": [(n, round(v, 2)) for n, v in top]}


class Monobank:
    URL = "https://api.monobank.ua/personal"

    def __init__(self, token: str):
        self.token = token
        self.cache: dict = {}

    def _get(self, path: str, ttl: int = 65):
        # Monobank дозволяє 1 запит виписки на хвилину — кешуємо
        hit = self.cache.get(path)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        r = requests.get(self.URL + path, headers={"X-Token": self.token}, timeout=20)
        if r.status_code == 429:
            raise RuntimeError("Monobank просить почекати хвилинку між запитами.")
        r.raise_for_status()
        self.cache[path] = (time.time(), r.json())
        return r.json()

    def main_account(self) -> dict:
        accs = self._get("/client-info", ttl=600).get("accounts", [])
        uah = [a for a in accs if a.get("currencyCode") == 980] or accs
        return max(uah, key=lambda a: a.get("balance", 0)) if uah else {}

    def balance(self) -> str:
        a = self.main_account()
        return f"Баланс гривневої картки: {a.get('balance', 0) / 100:.2f} грн." if a else "Не бачу рахунків."

    def spending(self, days: int) -> str:
        days = max(1, min(int(days), 31))                # Monobank віддає виписку максимум за 31 день
        a = self.main_account()
        now = int(time.time())
        items = self._get(f"/statement/{a.get('id', '0')}/{now - days * 86400}/{now}")
        s = spending_summary(items)
        if not s["total"]:
            return f"За останні {days} дн. витрат не бачу."
        top = ", ".join(f"{n} — {v:.0f} грн" for n, v in s["top"])
        return f"Витрати за {days} дн.: {s['total']:.0f} грн. Найбільше: {top}."


def _dec(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


class Gmail:
    def __init__(self, address: str, app_password: str):
        self.address, self.password = address, app_password

    def unread(self, limit: int = 10) -> str:
        with imaplib.IMAP4_SSL("imap.gmail.com") as m:
            m.login(self.address, self.password)
            m.select("INBOX", readonly=True)              # лише читання — листи лишаються непрочитаними
            _, data = m.search(None, "UNSEEN")
            ids = data[0].split()[-limit:]
            if not ids:
                return "Нових листів немає."
            lines = []
            for i in reversed(ids):
                _, msg_data = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                msg = email.message_from_bytes(msg_data[0][1])
                sender = _dec(msg.get("From")).split("<")[0].strip().strip('"')
                lines.append(f"- від {sender}: {_dec(msg.get('Subject'))}")
            return f"Непрочитаних: {len(data[0].split())}. Останні:\n" + "\n".join(lines)
