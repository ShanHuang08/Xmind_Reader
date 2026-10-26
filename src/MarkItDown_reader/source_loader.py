"""Acquire supported sources without touching legacy output directories."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import io
import warnings

from MarkItDown_reader.contracts import ContractError, digest, require, strict_json, json_text
from MarkItDown_reader.registry import OPENAPI_PREFIX


def version_of(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def display_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def is_openapi(data) -> bool:
    return isinstance(data, dict) and ("openapi" in data or "swagger" in data) and isinstance(data.get("paths"), dict)


def acquire(args) -> dict:
    if args.url:
        from url_reader.url_fetcher import fetch_url
        try:
            result = fetch_url(args.url, args.username or "", args.password or "", args.timeout or 30)
        except Exception as exc:
            raise ContractError(f"URL acquisition failed ({type(exc).__name__}); check network/authentication") from None
        media = result.content_type.split(";", 1)[0].lower().strip()
        if media in {"text/html", "application/xhtml+xml"}:
            kind = "html"
        elif media in {"text/markdown", "text/x-markdown"}:
            kind = "markdown"
        elif media == "application/json" or media.endswith("+json"):
            require(is_openapi(strict_json(result.text)), "Remote JSON is not OpenAPI")
            kind = "openapi"
        else:
            raise ContractError(f"Unsupported URL content type: {media}; download PDFs locally")
        raw = result.text.encode("utf-8")
        return {"bytes": raw, "kind": kind, "locator_hash": digest(args.url),
                "source_name": display_url(result.final_url), "acquisition": result.fetch_method,
                "acquired_sha256": result.sha256, "charset": "utf-8"}
    path = Path(args.input).resolve()
    require(path.is_file(), "Input is not a file")
    kind = {".pdf": "pdf", ".html": "html", ".htm": "html", ".md": "markdown",
            ".markdown": "markdown", ".json": "openapi", ".openapi": "openapi"}.get(path.suffix.lower())
    require(kind is not None, "Unsupported input format")
    raw = path.read_bytes()
    return {"bytes": raw, "kind": kind, "locator_hash": digest(str(path)), "source_name": path.name,
            "acquisition": "local", "acquired_sha256": digest(raw), "charset": None}


def converter_signature(kind: str, backend: str | None) -> dict:
    if kind in {"markdown", "openapi"}:
        return {"name": kind + "_passthrough", "version": "1"}
    packages = ("pymupdf4llm", "pdfplumber") if backend == "legacy" else (
        "markitdown", "pdfminer.six", "pdfplumber", "markdownify", "beautifulsoup4")
    return {"name": backend or "markitdown", "versions": {p: version_of(p) for p in packages},
            "preprocessing": "preserve-body-v1"}


def convert(source: dict, backend: str | None, local_path: str | None) -> tuple[str, list[str]]:
    raw, kind = source["bytes"], source["kind"]
    if kind == "openapi":
        data = strict_json(raw.decode("utf-8-sig"))
        require(is_openapi(data), "JSON input is not an OpenAPI document")
        return OPENAPI_PREFIX + json_text(data) + "\n", []
    if kind == "markdown":
        return raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n"), []
    if backend == "legacy":
        require(kind == "pdf" and bool(local_path), "Legacy converter only supports local PDF")
        from pdf_reader.pdf_markdown_reader import pdf_to_markdown
        return pdf_to_markdown(Path(local_path)), ["Explicit legacy converter"]
    try:
        from markitdown import MarkItDown, StreamInfo
    except (ImportError, OSError) as exc:
        raise ContractError("MarkItDown unavailable; install requirements-reader.txt in an isolated environment") from exc
    converter = MarkItDown(enable_plugins=False)
    info = StreamInfo(extension=".pdf" if kind == "pdf" else ".html",
                      mimetype="application/pdf" if kind == "pdf" else "text/html",
                      charset=source.get("charset"))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = converter.convert_stream(io.BytesIO(raw), stream_info=info)
        except Exception as exc:
            raise ContractError(f"{kind.upper()} conversion failed ({type(exc).__name__})") from None
    return result.markdown.replace("\r\n", "\n").replace("\r", "\n"), [str(w.message) for w in caught]
