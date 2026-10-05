from agent.services import mcc_name, spending_summary
from agent.tools import Tools

CFG = {"apps": {}, "search": {"url": "http://x"}, "openwebui": {}}


def test_spending_summary():
    items = [{"amount": -25000, "mcc": 5411}, {"amount": -10000, "mcc": 5411},
             {"amount": -5000, "mcc": 5814}, {"amount": 100000, "mcc": 4829}]
    s = spending_summary(items)
    assert s["total"] == 400.0 and s["top"][0] == ("продукти", 350.0)
    assert mcc_name(9999) == "інше"


def test_not_configured_messages():
    t = Tools(CFG)
    assert "не підключений" in t.call("money_spending", {"days": 7})
    assert "не підключений" in t.call("mail_unread", {})
