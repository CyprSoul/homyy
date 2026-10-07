from agent.kiwix import Kiwix

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <channel><title>Search: самвидав</title>
    <item><title>Самвидав</title><link>/content/wikipedia_uk_all_nopic_2026-09/A/Самвидав</link>
      <description>Самвидав — поширення в СРСР…</description></item>
    <item><title>Тамвидав</title><link>/content/wikipedia_uk_all_nopic_2026-09/A/Тамвидав</link></item>
  </channel></rss>"""


def test_parse_search_results():
    found = Kiwix.parse_results(RSS)
    assert found[0] == ("Самвидав", "/content/wikipedia_uk_all_nopic_2026-09/A/Самвидав")
    assert len(found) == 2 and Kiwix.parse_results("не xml") == []


def test_wiki_tool(monkeypatch):
    from agent.tools import Tools
    import agent.kiwix as kmod
    cfg = {"apps": {}, "search": {"url": "http://x"}, "openwebui": {}, "kiwix": {"url": "http://kiwix"}}
    assert "wiki" in {s["function"]["name"] for s in Tools(cfg).schemas()}
    assert "wiki" not in {s["function"]["name"] for s in Tools({**cfg, "kiwix": {}}).schemas()}
    monkeypatch.setattr(kmod.Kiwix, "search", lambda self, q, limit=5: Kiwix.parse_results(RSS))
    monkeypatch.setattr(kmod.Kiwix, "article", lambda self, link, limit=3500: "Самвидав — заборонена література…")
    out = Tools(cfg).call("wiki", {"query": "самвидав"})
    assert "«Самвидав»" in out and "заборонена" in out and "Тамвидав" in out
