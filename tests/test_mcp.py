import shutil
import sys
from pathlib import Path

import pytest

from agent import tools as tools_mod
from agent.mcp_hub import MCPHub

DEMO = Path(__file__).parent / "data" / "demo_mcp_server.py"


@pytest.mark.skipif(not __import__("importlib").util.find_spec("mcp"), reason="немає пакета mcp")
def test_mcp_connector_tools_reach_gemma(monkeypatch):
    hub = MCPHub({"demo": {"command": sys.executable, "args": [str(DEMO)]},
                  "broken": {"command": "no-such-command-xyz"}}, log=lambda *a: None)
    hub.start(30)
    monkeypatch.setattr(tools_mod, "MCP_HUB", hub)
    t = tools_mod.Tools({"apps": {}, "search": {"url": "http://x"}, "openwebui": {}})
    names = {s["function"]["name"] for s in t.schemas()}
    assert {"demo__add", "demo__greet", "web_search"} <= names       # і свої, і з конектора
    assert t.call("demo__add", {"a": 2, "b": 3}) == "5"
    assert t.call("demo__greet", {"name": "Ігор"}) == "Привіт, Ігор!"
