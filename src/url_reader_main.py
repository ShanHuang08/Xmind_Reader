"""CLI for supplementary vendor API URL reader."""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from pdf_reader.pdf_endpoint_indexer import build_endpoint_index
from url_reader.action_indexer import build_action_index
from url_reader.html_markdown_reader import html_to_markdown
from url_reader.openapi_reader import openapi_to_markdown
from url_reader.url_exporter import (
    clean_extracted_outputs,
    export_endpoint_index,
    export_full_text,
    export_manifest,
    export_sections,
    export_validation_report,
)
from url_reader.url_fetcher import UrlReadError, fetch_url, is_openapi_like, load_openapi_json
from url_reader.url_section_chunker import chunk_sections


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse supplementary vendor API URL docs into Codex-friendly retrieval files."
    )
    parser.add_argument("--url", default="", help="Vendor API document URL.")
    parser.add_argument("--html", default="", help="Local HTML file exported from a vendor API document page.")
    parser.add_argument("--vendor", default="", help="Vendor folder name. If omitted, inferred from URL host.")
    parser.add_argument("--username", default="", help="Optional HTTP Basic Auth username.")
    parser.add_argument("--password", default="", help="Optional HTTP Basic Auth password.")
    parser.add_argument(
        "--output",
        default="new_vendor_detail",
        help=(
            "Output root folder or direct vendor_url folder. Default: new_vendor_detail. "
            "If the path ends with vendor_url, it is used directly."
        ),
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds. Default: 30")
    parser.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    vendor = normalize_vendor_name(args.vendor or infer_vendor_name(args.url))
    output_dir = resolve_output_dir(Path(args.output), vendor)

    try:
        if args.html:
            result = _load_local_html(Path(args.html), args.url)
        else:
            if not args.url:
                raise ValueError("Either --url or --html is required.")
            result = fetch_url(args.url, args.username, args.password, args.timeout)
        validation = {
            "readable": bool(result.text.strip()),
            "source_url": args.url or str(args.html),
            "final_url": result.final_url,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "content_sha256": result.sha256,
            "fetch_method": result.fetch_method,
            "requires_auth": bool(args.username or args.password),
            "text_length": len(result.text),
        }
        export_validation_report(validation, output_dir)
        if not validation["readable"]:
            clean_extracted_outputs(output_dir)
            export_manifest(vendor, args.url, result.final_url, validation, 0, 0, output_dir)
            LOGGER.warning("[%s] URL returned no readable text: %s", vendor, args.url)
            return 0

        if is_openapi_like(result):
            markdown = openapi_to_markdown(load_openapi_json(result.text), result.final_url)
            reader_mode = "openapi"
        else:
            markdown = html_to_markdown(result.text, result.final_url)
            reader_mode = "html"

        export_full_text(markdown, output_dir)
        endpoint_index = _merge_indexes(build_endpoint_index(markdown), build_action_index(markdown))
        sections = chunk_sections(markdown, endpoint_index, result.final_url)
        section_paths = export_sections(sections, output_dir)
        export_endpoint_index(_attach_section_files(endpoint_index, section_paths), output_dir)
        export_manifest(vendor, args.url or str(args.html), result.final_url, validation, len(endpoint_index), len(sections), output_dir)

        LOGGER.info("[%s] URL readable: %s", vendor, validation["readable"])
        LOGGER.info("[%s] Reader mode: %s", vendor, reader_mode)
        LOGGER.info("[%s] Endpoints detected: %s", vendor, len(endpoint_index))
        LOGGER.info("[%s] Section JSON files generated: %s", vendor, len(sections))
        LOGGER.info("[%s] URL reader output written to %s", vendor, output_dir)
        return 0
    except (OSError, UrlReadError, ValueError) as exc:
        LOGGER.exception("Failed to process URL %s: %s", args.url or args.html, exc)
        return 1


def resolve_output_dir(output: Path, vendor: str) -> Path:
    if output.name.lower() == "vendor_url":
        return output
    return output / vendor / "vendor_url"


def infer_vendor_name(url: str) -> str:
    host = urlparse(url).hostname or "Unknown_Vendor"
    host = re.sub(r"^docs\.", "", host, flags=re.IGNORECASE)
    host = re.sub(r"\.[A-Za-z]{2,}$", "", host)
    return host.replace(".", "_")


def normalize_vendor_name(value: str) -> str:
    name = value.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_-")
    return name or "Unknown_Vendor"


def _load_local_html(html_path: Path, source_url: str):
    from hashlib import sha256
    from url_reader.url_fetcher import UrlFetchResult

    raw = html_path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    content_type = "application/json; charset=UTF-8" if _looks_like_openapi_json(html_path, text) else "text/html; charset=UTF-8"
    return UrlFetchResult(
        url=source_url or str(html_path),
        final_url=source_url or str(html_path),
        status_code=200,
        content_type=content_type,
        text=text,
        sha256=sha256(raw).hexdigest(),
        fetch_method="local_html",
    )


def _looks_like_openapi_json(path: Path, text: str) -> bool:
    if path.suffix.lower() not in {".json", ".openapi"} and "{" not in text[:20]:
        return False
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and (
        "openapi" in payload or "swagger" in payload or "paths" in payload
    )


def _attach_section_files(endpoint_index: list[dict], section_paths: list[Path]) -> list[dict]:
    result = []
    for endpoint, section_path in zip(endpoint_index, section_paths):
        item = dict(endpoint)
        item["section_file"] = f"sections/{section_path.name}"
        result.append(item)
    return result


def _merge_indexes(endpoint_index: list[dict], action_index: list[dict]) -> list[dict]:
    merged = list(endpoint_index)
    seen = {(item.get("method", ""), item.get("endpoint", "")) for item in merged}
    for item in action_index:
        key = (item.get("method", ""), item.get("endpoint", ""))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return sorted(merged, key=lambda item: item.get("line_index", 0))


if __name__ == "__main__":
    raise SystemExit(main())
