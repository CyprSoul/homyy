import requests

from agent import tts


def test_fallback_voice_used_when_primary_down(monkeypatch):
    cfg = {"tts": {"url": "http://primary", "voice": "Марічка Штирбулова", "model": "multi",
                   "fallback": {"url": "http://fallback", "voice": "uk-UA-PolinaNeural"}}}
    calls = []

    def fake_request(v, sentence):
        calls.append(v["url"])
        if v["url"] == "http://primary":
            raise requests.ConnectionError("down")
        return b"mp3"

    monkeypatch.setattr(tts.Speaker, "_request", staticmethod(fake_request))
    monkeypatch.setattr(tts.miniaudio, "decode",
                        lambda data, **k: type("D", (), {"samples": bytes(4)})())
    sp = tts.Speaker(cfg, audio=None)
    assert len(sp._synth("Привіт")) == 2
    assert calls == ["http://primary", "http://fallback"]


def test_warm_caches_phrase_in_background(monkeypatch):
    cfg = {"tts": {"url": "http://primary", "voice": "Марічка Штирбулова", "model": "multi"}}
    monkeypatch.setattr(tts.Speaker, "_request", staticmethod(lambda v, s: b"mp3"))
    monkeypatch.setattr(tts.miniaudio, "decode",
                        lambda data, **k: type("D", (), {"samples": bytes(4)})())
    sp = tts.Speaker(cfg, audio=None)
    sp.warm(["Так?"])
    sp.pool.shutdown(wait=True)
    assert "Так?" in sp.cache
