from agent.stt_bench import PHRASES, normalize, word_errors


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
