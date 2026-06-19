"""Convert readable PDFs into Markdown."""

from __future__ import annotations

from pathlib import Path

from .pdf_validator import PdfReadError


def pdf_to_markdown(pdf_path: Path) -> str:
    try:
        import pymupdf4llm
    except ImportError:
        return _pdf_to_markdown_with_pdfplumber(pdf_path)

    try:
        markdown = pymupdf4llm.to_markdown(str(pdf_path))
    except Exception as exc:
        raise PdfReadError(f"Failed to convert PDF to Markdown: {pdf_path}") from exc

    return markdown or ""


def _pdf_to_markdown_with_pdfplumber(pdf_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise PdfReadError("pymupdf4llm is not installed and pdfplumber fallback is unavailable.") from exc

    parts: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as document:
            for page_number, page in enumerate(document.pages, start=1):
                text = (page.extract_text(x_tolerance=1, y_tolerance=3) or "").strip()
                if text:
                    parts.append(f"\n\n# Page {page_number}\n\n{text}")
                for table in page.extract_tables() or []:
                    table_markdown = _table_to_markdown(table)
                    if table_markdown:
                        parts.append(table_markdown)
    except Exception as exc:
        raise PdfReadError(f"Failed to convert PDF to Markdown with pdfplumber: {pdf_path}") from exc
    return "\n\n".join(parts).strip() + "\n"


def _table_to_markdown(table: list[list[str | None]]) -> str:
    rows = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in table if row]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header = rows[0]
    separator = ["---"] * width
    body = rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)
