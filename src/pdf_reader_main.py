"""CLI for supplementary PDF vendor API reader."""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

from pdf_reader.pdf_endpoint_indexer import build_endpoint_index
from pdf_reader.pdf_exporter import (
    clean_extracted_outputs,
    export_endpoint_index,
    export_full_text,
    export_manifest,
    export_sections,
    export_validation_report,
)
from pdf_reader.pdf_markdown_reader import pdf_to_markdown
from pdf_reader.pdf_section_chunker import chunk_sections
from pdf_reader.pdf_validator import PdfReadError, validate_pdf


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse supplementary vendor API PDF docs into Codex-friendly retrieval files."
    )
    parser.add_argument("--pdf", required=True, help="PDF file path.")
    parser.add_argument("--vendor", default="", help="Vendor folder name. If omitted, inferred from PDF file name.")
    parser.add_argument(
        "--output",
        default="new_vendor_detail",
        help=(
            "Output root folder or direct vendor_pdf folder. Default: new_vendor_detail. "
            "If the path ends with vendor_pdf, it is used directly."
        ),
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    pdf_path = Path(args.pdf)
    vendor = normalize_vendor_name(args.vendor or infer_vendor_name(pdf_path))
    output_dir = resolve_output_dir(Path(args.output), vendor)

    try:
        validation = validate_pdf(pdf_path)
        export_validation_report(validation, output_dir)
        if not validation["readable"]:
            clean_extracted_outputs(output_dir)
            LOGGER.warning("%s OCR is required but OCR is out of scope. Skip PDF extraction.", pdf_path.name)
            export_manifest(vendor, pdf_path.name, validation, 0, 0, output_dir)
            LOGGER.info("[%s] Validation report written to %s", vendor, output_dir / "validation_report.json")
            return 0

        markdown = pdf_to_markdown(pdf_path)
        export_full_text(markdown, output_dir)
        endpoint_index = build_endpoint_index(markdown)
        sections = chunk_sections(markdown, endpoint_index, pdf_path.name)
        section_paths = export_sections(sections, output_dir)
        export_endpoint_index(_attach_section_files(endpoint_index, section_paths), output_dir)
        export_manifest(vendor, pdf_path.name, validation, len(endpoint_index), len(sections), output_dir)

        LOGGER.info("[%s] PDF readable: %s", vendor, validation["readable"])
        LOGGER.info("[%s] OCR required: %s", vendor, validation["ocr_required"])
        LOGGER.info("[%s] Endpoints detected: %s", vendor, len(endpoint_index))
        LOGGER.info("[%s] Section JSON files generated: %s", vendor, len(sections))
        LOGGER.info("[%s] PDF reader output written to %s", vendor, output_dir)
        return 0
    except (FileNotFoundError, OSError, PdfReadError, ValueError) as exc:
        LOGGER.exception("Failed to process PDF %s: %s", pdf_path, exc)
        return 1


def resolve_output_dir(output: Path, vendor: str) -> Path:
    if output.name.lower() == "vendor_pdf":
        return output
    return output / vendor / "vendor_pdf"


def infer_vendor_name(pdf_path: Path) -> str:
    name = pdf_path.stem
    name = re.sub(r"(?i)(_?integration.*|_?api.*|_?spec.*|_?document.*)$", "", name).strip("_- ")
    return name or "Unknown_Vendor"


def normalize_vendor_name(value: str) -> str:
    name = value.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_-")
    return name or "Unknown_Vendor"


def _attach_section_files(endpoint_index: list[dict], section_paths: list[Path]) -> list[dict]:
    result = []
    for endpoint, section_path in zip(endpoint_index, section_paths):
        item = dict(endpoint)
        item["section_file"] = f"sections/{section_path.name}"
        result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
