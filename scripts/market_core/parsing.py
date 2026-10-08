"""Parse provider data as data, including simple JavaScript assignments; never evaluate it."""
import json
import re
from html.parser import HTMLParser


def assigned_json(text, variable):
    prefix = re.match(r"\s*(?:var\s+)?" + re.escape(variable) + r"\s*=\s*", text.lstrip("\ufeff"))
    if not prefix:
        raise ValueError("Expected provider data assignment was not found")
    payload = text.lstrip("\ufeff")[prefix.end():]
    value, end = json.JSONDecoder().raw_decode(payload)
    if payload[end:].strip() not in {"", ";"}:
        raise ValueError("Unexpected executable content after provider data")
    return value


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


def html_text(text):
    parser = PlainHTML()
    parser.feed(text)
    return "\n".join(parser.parts)

