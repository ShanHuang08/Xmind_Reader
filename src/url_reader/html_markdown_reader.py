"""Convert HTML API docs into compact Markdown."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser


def html_to_markdown(html: str, source_url: str) -> str:
    """Convert HTML to Markdown with optional third-party helpers."""
    cleaned = _remove_noise(html)
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(cleaned, "html.parser")
        for selector in ("script", "style", "noscript", "svg", "canvas"):
            for node in soup.select(selector):
                node.decompose()
        for selector in ("nav", "footer", "aside"):
            for node in soup.select(selector):
                node.decompose()
        main = soup.find("main") or soup.find("article") or soup.body or soup
        try:
            from markdownify import markdownify as md

            markdown = md(str(main), heading_style="ATX")
        except Exception:
            markdown = _simple_html_to_markdown(str(main))
    except Exception:
        markdown = _simple_html_to_markdown(cleaned)

    markdown = _normalize_markdown(markdown)
    if source_url and source_url not in markdown[:500]:
        markdown = f"# Source URL\n\n{source_url}\n\n{markdown}"
    return markdown.strip() + "\n"


def _remove_noise(html: str) -> str:
    html = re.sub(r"(?is)<script\b.*?</script>", "", html)
    html = re.sub(r"(?is)<style\b.*?</style>", "", html)
    html = re.sub(r"(?is)<!--.*?-->", "", html)
    return html


def _normalize_markdown(markdown: str) -> str:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    markdown = re.sub(r"[\u200b-\u200f\ufeff]", "", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    lines = [line.rstrip() for line in markdown.splitlines()]
    return "\n".join(lines).strip()


def _simple_html_to_markdown(html: str) -> str:
    parser = _SimpleMarkdownParser()
    parser.feed(html)
    return parser.markdown


class _SimpleMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.heading_level = 0
        self.in_table_cell = False
        self.current_row: list[str] = []

    @property
    def markdown(self) -> str:
        text = "".join(self.parts)
        text = unescape(text)
        return _normalize_markdown(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_level = int(tag[1])
            self.parts.append("\n\n" + "#" * self.heading_level + " ")
        elif tag in {"p", "div", "section", "article", "br"}:
            self.parts.append("\n")
        elif tag in {"ul", "ol"}:
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in {"th", "td"}:
            self.in_table_cell = True
            self.current_row.append("")
        elif tag == "tr":
            self.current_row = []
        elif tag == "pre":
            self.parts.append("\n\n```text\n")
        elif tag == "code":
            self.parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_level = 0
            self.parts.append("\n")
        elif tag in {"p", "div", "section", "article"}:
            self.parts.append("\n")
        elif tag in {"th", "td"}:
            self.in_table_cell = False
        elif tag == "tr" and self.current_row:
            cells = [cell.strip() for cell in self.current_row]
            self.parts.append("\n| " + " | ".join(cells) + " |")
            self.current_row = []
        elif tag == "pre":
            self.parts.append("\n```\n")
        elif tag == "code":
            self.parts.append("`")

    def handle_data(self, data: str) -> None:
        text = re.sub(r"\s+", " ", data)
        if not text.strip():
            return
        if self.in_table_cell and self.current_row:
            self.current_row[-1] += text
        else:
            self.parts.append(text)
