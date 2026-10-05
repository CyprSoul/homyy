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


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = args[0] if args else "http://localhost:8003"
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
