"""Validate whether a PDF has extractable text before conversion."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class PdfReadError(RuntimeError):
    """Raised when a PDF cannot be opened or read."""


def validate_pdf(pdf_path: Path) -> dict[str, Any]:
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if not pdf_path.is_file():
        raise PdfReadError(f"PDF path is not a file: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise PdfReadError(f"Unsupported file extension: {pdf_path}")

    try:
        return _validate_with_pymupdf(pdf_path)
    except ImportError:
        return _validate_with_pdfplumber(pdf_path)


def _validate_with_pymupdf(pdf_path: Path) -> dict[str, Any]:
    import fitz

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:  # PyMuPDF raises several concrete exception types.
        raise PdfReadError(f"Cannot open PDF: {pdf_path}") from exc

    try:
        page_count = document.page_count
        total_text_length = 0
        for page in document:
            total_text_length += len(page.get_text("text").strip())
    finally:
        document.close()

    avg_text_length = int(total_text_length / page_count) if page_count else 0
    readable = page_count > 0 and total_text_length >= max(100, page_count * 20)
    return {
        "file": pdf_path.name,
        "readable": readable,
        "ocr_required": not readable,
        "page_count": page_count,
        "total_text_length": total_text_length,
        "avg_text_length_per_page": avg_text_length,
        "status": (
            "PDF has extractable text"
            if readable
            else "PDF appears to be image-based. OCR is required and skipped."
        ),
        "reader": "pymupdf",
    }


def _validate_with_pdfplumber(pdf_path: Path) -> dict[str, Any]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise PdfReadError("PyMuPDF is not installed and pdfplumber fallback is unavailable.") from exc

    try:
        with pdfplumber.open(pdf_path) as document:
            page_count = len(document.pages)
            total_text_length = 0
            for page in document.pages:
                total_text_length += len((page.extract_text() or "").strip())
    except Exception as exc:
        raise PdfReadError(f"Cannot open PDF: {pdf_path}") from exc

    avg_text_length = int(total_text_length / page_count) if page_count else 0
    readable = page_count > 0 and total_text_length >= max(100, page_count * 20)
    return {
        "file": pdf_path.name,
        "readable": readable,
        "ocr_required": not readable,
        "page_count": page_count,
        "total_text_length": total_text_length,
        "avg_text_length_per_page": avg_text_length,
        "status": (
            "PDF has extractable text"
            if readable
            else "PDF appears to be image-based. OCR is required and skipped."
        ),
        "reader": "pdfplumber",
    }
