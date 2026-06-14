"""Convert readable PDFs into Markdown using pymupdf4llm."""

from __future__ import annotations

from pathlib import Path

from .pdf_validator import PdfReadError


def pdf_to_markdown(pdf_path: Path) -> str:
    try:
        import pymupdf4llm
    except ImportError as exc:
        raise PdfReadError("pymupdf4llm is not installed. Install dependencies first.") from exc

    try:
        markdown = pymupdf4llm.to_markdown(str(pdf_path))
    except Exception as exc:
        raise PdfReadError(f"Failed to convert PDF to Markdown: {pdf_path}") from exc

    return markdown or ""
