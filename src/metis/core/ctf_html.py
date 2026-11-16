"""Bounded HTML intake. Page contents remain untrusted data, never instructions."""
from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser


class Page(HTMLParser):
    def __init__(self, body: str, url: str):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.forms: list[dict] = []
        self.links: list[dict] = []
        self.nodes: list[dict] = []
        self.stack: list[tuple[str, int | None]] = []
        self.text_parts: list[str] = []
        self.text_size = 0
        self.title = ""
        self.categories: list[str] = []
        self._form: dict | None = None
        self._link: dict | None = None
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if len(self.stack) > 64:
            raise ValueError("HTML nesting exceeds limit")
        if tag == "form":
            if len(self.forms) >= 32:
                raise ValueError("too many forms")
            self._form = {"action": urllib.parse.urljoin(self.url, values.get("action") or self.url),
                          "method": (values.get("method") or "get").upper(), "fields": []}
            self.forms.append(self._form)
        if tag in {"input", "button", "textarea", "select"} and self._form is not None:
            if len(self._form["fields"]) >= 64:
                raise ValueError("too many form fields")
            name = values.get("name")
            if name:
                self._form["fields"].append({"name": name[:256],
                                            "type": (values.get("type") or tag).lower(),
                                            "value": (values.get("value") or "")[:8192]})
        if tag == "a" and values.get("href") and len(self.links) < 256:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(values["href"]).query)
            for declared in query.get("q", []):
                match = re.fullmatch(r"category:(web|crypto|rev|pwn|forensics|misc)", declared, re.IGNORECASE)
                if match:
                    self.categories.append(match.group(1).lower())
            self._link = {"url": urllib.parse.urljoin(self.url, values["href"]), "text": "",
                          "download": "download" in values}
            self.links.append(self._link)
        node = None
        if (values.get("id") or values.get("class")) and len(self.nodes) < 1024:
            node = len(self.nodes)
            self.nodes.append({"id": values.get("id") or "", "classes": (values.get("class") or "").split(),
                               "tag": tag, "text": ""})
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, node))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag == "form":
            self._form = None
        if tag == "a":
            self._link = None

    def handle_data(self, text):
        if any(tag in {"script", "style"} for tag, _ in self.stack):
            return
        if any(tag == "title" for tag, _ in self.stack):
            self.title = (self.title + text)[:256]
        if self.text_size < 65_536:
            piece = text[:65_536 - self.text_size]
            self.text_parts.append(piece)
            self.text_size += len(piece)
        if self._link is not None:
            self._link["text"] = (self._link["text"] + text)[:256]
        for _, index in self.stack:
            if index is not None:
                self.nodes[index]["text"] = (self.nodes[index]["text"] + text)[:2048]

    @property
    def text(self) -> str:
        return "\n".join(part.strip() for part in self.text_parts if part.strip())

    def selected_text(self, selector: str) -> str | None:
        if not re.fullmatch(r"[#.][A-Za-z0-9_-]{1,80}", selector):
            raise ValueError("verdict selector must be one #id or .class")
        values = [node["text"].strip() for node in self.nodes
                  if (node["id"] == selector[1:] if selector.startswith("#")
                      else selector[1:] in node["classes"])]
        return values[0] if len(values) == 1 else None


def display_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def public_forms(page: Page) -> list[dict]:
    return [{"index": index, "action": display_url(form["action"]), "method": form["method"],
             "fields": [{"name": field["name"], "type": field["type"],
                         "has_default": bool(field["value"])} for field in form["fields"]]}
            for index, form in enumerate(page.forms)]
