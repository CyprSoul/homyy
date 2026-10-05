"""Прослуховування голосів: кожен голос каже ту саму фразу, файли — в C:\\homyy\\voices.

Запуск: .venv\\Scripts\\python -m agent.voice_audition [адреса API]
"""
import os
import sys
from pathlib import Path

import requests

PHRASE = ("Привіт, Ігоре! Я Хомі. Сьогодні двадцять перше жовтня, на вулиці дванадцять градусів. "
          "Хочеш, я складу план тренувань на завтра?")
OUT = Path("C:/homyy/voices") if sys.platform == "win32" else Path.home() / "homyy-voices"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8003"
    r = requests.get(f"{base}/v1/audio/voices", timeout=60)
    if not r.ok:
        print(f"Сервер голосу ще не готовий або помилка ({r.status_code}): {r.text[:300]}")
        print("Подивись журнал: docker logs tts_uk_api --tail 40   і   docker logs tts_uk_gradio --tail 40")
        return
    voices = r.json().get("voices", [])
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
