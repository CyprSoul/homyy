"""Прослуховування голосів: кожен голос каже ту саму фразу, файли — в C:\\homyy\\voices.

Запуск: .venv\\Scripts\\python -m agent.voice_audition [адреса API]
"""
import os
import sys
from pathlib import Path

import requests

PHRASE = ("Привіт, Ігоре! Я Хомі. Сьогодні двадцять перше жовтня, на вулиці дванадцять градусів. "
          "Хочеш, я складу план тренувань на завтра?")
# Жіночі голоси StyleTTS2-Ukrainian (Хомі — дівчина). Повний список — з параметром --all.
FEMALE = ["Марина Панас", "Інна Гелевера", "Анастасія Павленко", "Вероніка Дорош", "Влада Муравець",
          "Вікторія Левченко", "Гаська Шиян", "Катерина Потапенко", "Людмила Чиркова", "Марися Нікітюк",
          "Марта Мольфар", "Марічка Штирбулова", "Олена Шверк", "Поліна Еккерт", "Слава Красовська",
          "Тетяна Гончарова", "Тетяна Лукинюк"]
OUT = Path("C:/homyy/voices") if sys.platform == "win32" else Path.home() / "homyy-voices"


ROUND2 = [
    ("1 знайомство", "Привіт, Ігоре! Я тут. Як пройшов твій день? Може, розкажеш, що цікавого сталося?"),
    ("2 наголоси", "Тимофію сьогодні шість місяців і сімнадцять днів. До Нового року лишилось вісімдесят вісім днів, "
                   "а на вулиці у Львові дванадцять градусів і легкий дощ."),
    ("3 емоції", "Ого, оце так новина! Я дуже рада за тебе. Але чесно, два плюс два — це все ж таки чотири, не п'ять!"),
    ("4 довга відповідь", "Добре, давай складемо план. Спершу п'ятнадцять хвилин розминки, потім три підходи "
                          "присідань по дванадцять разів, віджимання, планка на сорок секунд, і наприкінці розтяжка. "
                          "Пий воду між підходами, і не забудь відпочити."),
]


def final_round(base: str):
    """Друге коло: ті голоси, файли яких ти залишив у папці, читають складніші фрази."""
    favorites = sorted(p.stem for p in OUT.glob("*.mp3"))
    if not favorites:
        print(f"У {OUT} немає файлів — спершу запусти без --final і залиш у папці фаворитів.")
        return
    out = OUT / "фінал"
    out.mkdir(exist_ok=True)
    print(f"Фінал: {', '.join(favorites)}. Кожна читає {len(ROUND2)} фрази…")
    for v in favorites:
        for name, text in ROUND2:
            r = requests.post(f"{base}/v1/audio/speech", timeout=300,
                              json={"model": "multi", "voice": v, "input": text, "response_format": "mp3"})
            if r.ok:
                (out / f"{name} — {v}.mp3").write_bytes(r.content)
        print(f"  ✓ {v}")
    if sys.platform == "win32":
        os.startfile(out)
    print("Порівняй фрази з однаковим номером у різних голосів і скажи, хто переміг.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = args[0] if args else "http://localhost:8003"
    if "--final" in sys.argv:
        final_round(base)
        return
    voices = FEMALE
    if "--all" in sys.argv:
        r = requests.get(f"{base}/v1/audio/voices", timeout=60)   # є лише в новіших версіях сервера
        if r.ok:
            voices = r.json().get("voices", FEMALE)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Голосів: {len(voices)}. Записую зразки в {OUT} …")
    for v in voices:
        r = requests.post(f"{base}/v1/audio/speech", timeout=300,
                          json={"model": "multi", "voice": v, "input": PHRASE, "response_format": "mp3"})
        if r.ok:
            (OUT / f"{v}.mp3").write_bytes(r.content)
            print(f"  ✓ {v}")
        else:
            print(f"  ✗ {v}: {r.status_code} {r.text[:300]}")
    if sys.platform == "win32":
        os.startfile(OUT)
    print("Послухай і скажи, який голос найкращий для Хомі.")


if __name__ == "__main__":
    main()
