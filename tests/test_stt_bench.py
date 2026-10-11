import numpy as np

from agent.stt_bench import PHRASES, loud_seconds, normalize, word_errors


def test_loud_seconds_ignores_silence_and_counts_speech():
    rate = 16000
    silence = np.zeros(rate, dtype=np.int16)                                   # 1 с повної тиші
    quiet_noise = (np.random.default_rng(0).standard_normal(rate) * 3).astype(np.int16)   # ≈ −80 дБ
    tone = (np.sin(np.linspace(0, 2000 * np.pi, rate)) * 3000).astype(np.int16)           # ≈ −23 дБ, 1 с
    assert loud_seconds(silence) == 0 and loud_seconds(quiet_noise) == 0
    assert 0.9 <= loud_seconds(np.concatenate([silence, tone, silence])) <= 1.05


def test_normalize_ignores_case_punctuation_and_latin_brands():
    assert normalize("Відкрий Discord!") == ["відкрий", "діскорд"]
    assert normalize("Запам’ятай — «так».") == ["запам'ятай", "так"]


def test_word_errors():
    ref = "відкрий папку з іграми"
    assert word_errors(ref, "Відкрий папку з іграми.") == 0
    assert word_errors(ref, "відкрий папку іграми") == 1            # пропуск слова
    assert word_errors(ref, "відкрий папку з іграми тут") == 1      # зайве слово
    assert word_errors(ref, "відкрий папку з іграх") == 1           # підміна
    assert word_errors(ref, "") == 4


def test_phrases_are_ukrainian_only():
    assert len(PHRASES) == 30
    assert not any(ch in "ыэъё" for p in PHRASES for ch in p.lower())
