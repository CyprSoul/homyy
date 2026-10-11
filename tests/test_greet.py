import json
import time
from datetime import datetime

from agent import greet as G
from agent.brain import Brain

CFG = {"user": {"name": "Ігор", "name_genitive": "Ігоря", "name_vocative": "Ігорю"},
       "ollama": {"url": "http://x", "model": "m"}, "apps": {}, "search": {"url": "http://x"}, "openwebui": {}}


def make_brain(monkeypatch, tmp_path, memories=(), replies=()):
    b = Brain(CFG)
    monkeypatch.setattr(Brain, "GREET_FILE", tmp_path / "g.json")
    monkeypatch.setattr(b, "_memories", lambda: list(memories))
    queue = list(replies)
    prompts = []

    def fake_ask(brain, prompt):
        prompts.append(prompt)
        return queue.pop(0) if queue else "Тут."
    monkeypatch.setattr(G, "ask_model", fake_ask)
    return b, prompts


def test_check_rejects_stock_phrases_presumptions_clock_and_personal():
    form = {"question": False}
    assert G.check("Привіт, Ігорю! Я вже тут і в строю.", form, []) == "шаблонний зворот"
    assert G.check("Знову в ігри затягнуло?", form, [])
    assert G.check("Бачу, ти занурений у ігри.", form, [])
    assert G.check("Ти просив відкрити сторінку, але не дав вказівок.", form, [])
    assert G.check("Я вже працюю, поки ти ще спиш.", form, [])
    assert G.check("Зараз 09:05, недільний ранок.", form, []) == "читає точний час"
    assert G.check("Пам'ятаю, що в тебе є син Андрій.", form, []) == "особисте (родина, здоров'я, гроші)"
    assert G.check("Як настрій?", form, []) == "питання, хоча не треба"
    assert G.check("Недільний вечір має свій затишок.", form, []) is None
    assert G.check("Hello there my friend how are you doing today", form, []) == "не українською"


def test_similar_to_recent_is_rejected_even_if_reworded():
    recent = ["Недільний вечір має особливий лінивий настрій."]
    assert G.too_similar("Недільний вечір має особливий лінивий вайб.", recent)
    assert G.too_similar("Недільний ранок. Тиха година.", ["Недільний ранок, тиха година."])
    assert not G.too_similar("Хей, я поруч.", recent)


def test_same_opening_in_a_row_is_rejected():
    assert G.too_similar("Ну що, Ігорю, як справи?", ["Ну що, Ігорю, ще не спиш?"])


def test_angles_vary_and_recent_angles_are_avoided(monkeypatch):
    ctx = {"memory": "любить каву"}
    seen = set()
    for _ in range(60):
        seen.add(G.pick_angle(ctx, [{"angle": "moment"}, {"angle": "wit"}], set()))
    assert seen and not (seen & {"moment", "wit"})                  # два останні кути не повторюються
    assert {"memory", "short", "curious"} & seen
    assert G.pick_angle({}, [], {"moment", "wit", "curious", "short"}) == "moment"   # нічого не лишилось — не падаємо


def test_available_angles_follow_what_is_true(monkeypatch, tmp_path):
    b, _ = make_brain(monkeypatch, tmp_path)
    ctx = G.gather(b, datetime.now(), [])
    assert "memory" not in ctx and "plan" not in ctx and "gap" not in ctx        # нічого не вигадуємо
    b.tools.jobs.add_reminder(30, "випити воду")
    assert "випити воду" in G.gather(b, datetime.now(), [])["plan"]
    just_now = [{"t": time.time() - 120, "text": "Тут."}]
    assert "перезапустила" in G.gather(b, datetime.now(), just_now)["gap"]
    long_ago = [{"t": time.time() - 12 * 3600, "text": "Тут."}]
    assert "год" in G.gather(b, datetime.now(), long_ago)["gap"]


def test_sensitive_memories_are_never_used_in_greeting(monkeypatch, tmp_path):
    memories = ["Ігор: у нього є син Андрій, який народився 5 травня 2025 року",
                "Ігор любить грати в комп'ютерні ігри", "Ігор приймає ліки від алергії"]
    b, _ = make_brain(monkeypatch, tmp_path, memories=memories)
    for _ in range(30):
        assert G.gather(b, datetime.now(), []).get("memory") == "Ігор любить грати в комп'ютерні ігри"


def test_prompt_has_one_angle_and_no_old_greetings(monkeypatch, tmp_path):
    b, prompts = make_brain(monkeypatch, tmp_path, replies=["Хей, я поруч.", "Недільний вечір, затишок."])
    first = b.greet()
    second = b.greet()
    assert first != second and len(prompts) == 2
    assert first not in prompts[1]                                   # старе привітання — не зразок для наслідування
    assert "Не вживай звороти" in prompts[0] and "не докоряй" in prompts[0]


def test_bad_greeting_is_retried_then_falls_back(monkeypatch, tmp_path):
    b, prompts = make_brain(monkeypatch, tmp_path, replies=["Я вже тут, в строю!", "Бачу, ти в іграх.", "Я вже працюю."])
    text = b.greet()
    assert len(prompts) == 3                                         # три спроби з різними кутами
    assert text and "в строю" not in text and "ігр" not in text.lower()   # запасне з готових, а не вигадка
    saved = json.loads((tmp_path / "g.json").read_text(encoding="utf-8"))
    assert saved[-1]["angle"] == "static"


def test_old_history_format_is_read_and_new_one_saved(monkeypatch, tmp_path):
    (tmp_path / "g.json").write_text(json.dumps(["Привіт, Ігорю! Я вже тут."]), encoding="utf-8")
    b, _ = make_brain(monkeypatch, tmp_path, replies=["Хей, я поруч."])
    assert b.greet() == "Хей, я поруч."
    saved = json.loads((tmp_path / "g.json").read_text(encoding="utf-8"))
    assert saved[0] == {"text": "Привіт, Ігорю! Я вже тут."} and saved[-1]["text"] == "Хей, я поруч." and saved[-1]["t"]


def test_emoji_stripped_unless_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(G.random, "random", lambda: 0.9)             # емодзі не дозволені, початок не вказаний
    b, _ = make_brain(monkeypatch, tmp_path, replies=["Хей, я поруч 😉"])
    assert b.greet() == "Хей, я поруч"
