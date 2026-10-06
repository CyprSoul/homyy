"""Переносить сфери thinking-orbs (MIT, © Jakub Antalik, Schoolees) у Хомі.

Бере зібраний dist/index.js, робить з нього звичайний скрипт (window.ThinkingOrbs) і замінює
сірі кольори точок на функцію __tint — щоб сфера світилась кольором стану Хомі.
Запуск: python scripts/vendor_orbs.py <шлях до клону thinking-orbs>
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
js = (src / "dist" / "index.js").read_text(encoding="utf-8")

js, n1 = re.subn(r"`rgba\(\$\{(\w+)\},\$\{\1\},\$\{\1\},\$\{(\w+)\}\)`", r"__tint(\1, \2)", js)
js, n2 = re.subn(r"`rgba\(250,250,250,\$\{(\w+)\}\)`", r"__tint(250, \1)", js)
m = re.search(r"export \{(.*?)\};\s*$", js, re.S)
pairs = [p.strip().split(" as ") for p in m.group(1).split(",") if p.strip()]
js = js[:m.start()] + "window.ThinkingOrbs = {" + ", ".join(f"{b}: {a}" for a, b in pairs) + "};\n"
assert n1 >= 2 and n2 >= 2, (n1, n2)

head = ("/* thinking-orbs — MIT License, (c) Jakub Antalik; adapted by Schoolees.\n"
        "   https://github.com/schoolees/thinking-orbs — vendored for Homyy (colours via __tint). */\n")
out = Path(__file__).resolve().parent.parent / "agent" / "orb_web"
(out / "thinking-orbs.js").write_text(head + js, encoding="utf-8")
(out / "LICENSE-thinking-orbs").write_text((src / "LICENSE").read_text(encoding="utf-8"), encoding="utf-8")
print(f"ok: {n1}+{n2} кольорів, експортів {len(pairs)}")
