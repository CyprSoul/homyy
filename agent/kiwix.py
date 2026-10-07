"""Українська Вікіпедія офлайн (Kiwix): факти без інтернету й без вигадок.

kiwix-serve (Docker, config/kiwix) роздає ZIM-файл Вікіпедії; тут — пошук і текст статті.
API kiwix-serve трохи різниться між версіями, тому кожен крок має запасний варіант.
"""
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urljoin

import requests


class Kiwix:
    def __init__(self, url: str, timeout: float = 8):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._books: list[str] | None = None

    def books(self) -> list[str]:
        """Назви ZIM-книжок на сервері (напр. wikipedia_uk_all_nopic_2026-09)."""
        if self._books:
            return self._books
        names: list[str] = []
        try:
            r = requests.get(f"{self.url}/catalog/v2/entries", timeout=self.timeout)
            if r.ok:
                names = re.findall(r"<name>([^<]+)</name>", r.text)
        except requests.RequestException:
            pass
        if not names:
            try:
                r = requests.get(self.url + "/", timeout=self.timeout)
                names = list(dict.fromkeys(re.findall(r'/content/([^/"?#]+)', r.text)))
            except requests.RequestException:
                pass
        self._books = names
        return names

    @staticmethod
    def parse_results(xml_text: str) -> list[tuple[str, str]]:
        """RSS-відповідь пошуку → [(заголовок, посилання)]."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        out = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link:
                out.append((title, link))
        return out

    def search(self, query: str, limit: int = 5) -> list[tuple[str, str]]:
        q = quote(query)
        books = self.books() or [""]
        for book in books[:3]:
            for url in (f"{self.url}/search?books.name={book}&pattern={q}&format=xml&pageLength={limit}",
                        f"{self.url}/search?content={book}&pattern={q}&format=xml&pageLength={limit}",
                        f"{self.url}/search?pattern={q}&format=xml&pageLength={limit}"):
                try:
                    r = requests.get(url, timeout=self.timeout)
                except requests.RequestException:
                    continue
                if r.ok:
                    found = self.parse_results(r.text)
                    if found:
                        return found[:limit]
        return []

    def article(self, link: str, limit: int = 3500) -> str:
        try:
            r = requests.get(urljoin(self.url + "/", link.lstrip("/")), timeout=self.timeout)
            r.raise_for_status()
            import trafilatura
            text = trafilatura.extract(r.text, include_comments=False, include_tables=False) or ""
        except Exception:  # noqa: BLE001
            return ""
        return " ".join(text.split())[:limit]
