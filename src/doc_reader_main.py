"""CLI for converting Confluence Word exports into vendor detail files."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any
import json

from doc_reader.doc_exporter import export_vendor_detail
from doc_reader.doc_extractor import extract_vendor_detail
from doc_reader.doc_parser import DocReadError, parse_vendor_doc


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert Confluence Word exports into Codex-friendly vendor details."
    )
    parser.add_argument(
        "--input",
        default="new_vendor_source",
        help="Document file, file name under new_vendor_source, or folder containing vendor docs.",
    )
    parser.add_argument(
        "--output",
        default="new_vendor_detail",
        help="Folder for generated vendor detail files.",
    )
    parser.add_argument("--vendor", default="", help="Optional vendor name override.")
    parser.add_argument("--force", action="store_true", help="Force regeneration even if source file is unchanged.")
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    files = resolve_doc_files(args.input, Path("new_vendor_source"))
    if files is None:
        return 1
    if not files:
        LOGGER.warning("No vendor documents found.")
        return 0

    failures = 0
    for doc_path in files:
        try:
            vendor = normalize_vendor_name(args.vendor or infer_vendor_name(doc_path))
            output_dir = Path(args.output) / vendor
            current_meta = source_meta(doc_path)
            existing_meta = load_source_meta(output_dir)
            if existing_meta == current_meta and not args.force:
                LOGGER.info("[%s] %s unchanged. Skip regeneration.", vendor, doc_path.name)
                LOGGER.info("[%s] Output already written to %s", vendor, output_dir)
                continue

            parsed = parse_vendor_doc(doc_path)
            detail = extract_vendor_detail(parsed, vendor)
            detail["source_meta"] = current_meta
            paths = export_vendor_detail(detail, Path(args.output))
            LOGGER.info("[%s] Parsed source: %s", vendor, doc_path)
            LOGGER.info("[%s] Endpoints: %s", vendor, len(detail.get("endpoints", [])))
            LOGGER.info("[%s] Error codes: %s", vendor, len(detail.get("error_codes", [])))
            LOGGER.info("[%s] Output written to %s", vendor, paths["api_summary"].parent)
        except (DocReadError, OSError, ValueError) as exc:
            failures += 1
            LOGGER.exception("Failed to process %s: %s", doc_path, exc)
    return 1 if failures else 0


def resolve_doc_files(input_value: str, default_input_dir: Path) -> list[Path] | None:
    target = Path(input_value)
    candidates = [target]
    if not target.is_absolute():
        candidates.append(default_input_dir / input_value)

    existing = next((candidate for candidate in candidates if candidate.exists()), None)
    if existing is None:
        LOGGER.error("Vendor source document/path does not exist: %s", input_value)
        if default_input_dir.exists():
            print_available_docs(default_input_dir)
        return None

    if existing.is_file():
        return [existing]
    if existing.is_dir():
        return sorted(
            file
            for file in existing.iterdir()
            if file.suffix.lower() in {".doc", ".docx", ".html", ".htm"}
        )
    LOGGER.error("Unsupported input path: %s", existing)
    return None


def source_meta(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "source_file": path.name,
        "source_path": str(path),
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def load_source_meta(vendor_output_dir: Path) -> dict[str, Any] | None:
    meta_path = vendor_output_dir / "source_meta.json"
    if not meta_path.exists():
        return None
    try:
        with meta_path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Cannot read source meta from %s: %s", meta_path, exc)
        return None


def print_available_docs(folder: Path) -> None:
    print("Available vendor source documents:")
    for file in sorted(folder.iterdir()):
        if file.suffix.lower() in {".doc", ".docx", ".html", ".htm"}:
            print(f"  - {file.name} [{normalize_vendor_name(infer_vendor_name(file))}]")


def infer_vendor_name(path: Path) -> str:
    name = path.stem
    name = re.sub(r"(?i)^vendor[_ -]*", "", name)
    name = re.sub(r"(?i)[_ -]*(api|document|doc|source|spec|confluence)$", "", name)
    return name or "NewVendor"


def normalize_vendor_name(value: str) -> str:
    name = value.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_-")
    return name or "NewVendor"


if __name__ == "__main__":
    raise SystemExit(main())
