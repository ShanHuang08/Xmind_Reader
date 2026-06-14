"""CLI entry point for Phase 2 XMind knowledge extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from chunker.knowledge_chunker import chunk_knowledge
from exporters.excel_exporter import export_excel
from exporters.json_exporter import (
    export_chunks,
    export_duplicate_report,
    export_extraction_report,
    export_raw,
    export_source_meta,
    export_summary,
)
from exporters.markdown_exporter import export_markdown
from extractor.knowledge_extractor import extract_knowledge
from parser.xmind_reader import XMindParseError, parse_xmind_file


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse XMind files into a reusable test case knowledge base."
    )
    parser.add_argument(
        "--input",
        default=None,
        help=(
            "XMind file, file name under input_xmind, or folder containing .xmind files. "
            "If omitted, input_xmind is scanned."
        ),
    )
    parser.add_argument("--output", default="xmind_detail", help="Folder for XMind detail files.")
    parser.add_argument(
        "--vendor",
        default="",
        help="Optional vendor folder name. If omitted, it is inferred from each XMind file name.",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    output_dir = Path(args.output)
    default_input_dir = Path("input_xmind")
    files = resolve_input_files(args.input, default_input_dir, output_dir)
    if files is None:
        return 1
    if not files:
        LOGGER.warning("No .xmind files found.")
        return 0
    if args.input is None and len(files) > 1:
        print_available_files(files, output_dir)
        LOGGER.info(
            "Please specify one file, for example: python main.py xmind --input %s",
            files[0].name,
        )
        return 0

    parsed_by_vendor = defaultdict(list)
    failures = 0
    for xmind_path in files:
        try:
            parsed = parse_xmind_file(xmind_path)
            vendor = normalize_vendor_name(args.vendor or infer_vendor_name(xmind_path))
            vendor_output_dir = output_dir / vendor
            existing_stats = load_existing_raw_stats(vendor_output_dir, xmind_path.stem)
            current_meta = source_meta(xmind_path)
            existing_meta = load_existing_source_meta(vendor_output_dir, xmind_path.stem)
            decision = processing_decision(parsed.get("stats", {}), existing_stats, current_meta, existing_meta)
            if decision == "skip_equal":
                LOGGER.info(
                    "[%s] %s unchanged (%s topics, %s test cases). Skip regeneration.",
                    vendor,
                    xmind_path.name,
                    parsed["stats"].get("topic_count", 0),
                    parsed["stats"].get("test_case_count", 0),
                )
                LOGGER.info("[%s] Output already written to %s", vendor, vendor_output_dir)
                continue
            if decision == "preserve_decrease":
                LOGGER.info(
                    "[%s] %s has fewer topics/test cases than existing output. Preserve current JSON/Markdown and skip.",
                    vendor,
                    xmind_path.name,
                )
                continue
            if decision == "raw_only":
                export_raw(parsed, vendor_output_dir, xmind_path.stem)
                export_source_meta(current_meta, vendor_output_dir, xmind_path.stem)
                if existing_meta:
                    parsed_by_vendor[vendor].append(parsed)
                    LOGGER.info(
                        "[%s] %s changed with same topic/test case count. Run case-level update.",
                        vendor,
                        xmind_path.name,
                    )
                else:
                    LOGGER.info(
                        "[%s] %s source meta initialized. Updated raw/source meta only.",
                        vendor,
                        xmind_path.name,
                    )
                continue

            parsed_by_vendor[vendor].append(parsed)
            export_raw(parsed, vendor_output_dir, xmind_path.stem)
            export_source_meta(current_meta, vendor_output_dir, xmind_path.stem)
        except (XMindParseError, OSError, ValueError) as exc:
            failures += 1
            LOGGER.exception("Failed to process %s: %s", xmind_path, exc)

    if not parsed_by_vendor:
        return 1 if failures else 0

    for vendor, parsed_files in sorted(parsed_by_vendor.items()):
        vendor_output_dir = output_dir / vendor
        current_knowledge = extract_knowledge(parsed_files)
        existing_cases = load_existing_cases(vendor_output_dir)
        change_stats = case_change_stats(existing_cases, current_knowledge["cases"])
        cases = merge_existing_and_new_cases(existing_cases, current_knowledge["cases"])
        report = build_vendor_report(cases, parsed_files)
        chunks = chunk_knowledge(cases)

        export_excel(cases, vendor_output_dir / "excel" / "knowledge_base.xlsx")
        export_summary(report, vendor_output_dir)
        export_extraction_report(report, chunks["duplicates"], vendor_output_dir)
        export_duplicate_report(chunks["duplicates"], vendor_output_dir)
        export_chunks(chunks["modules"], vendor_output_dir, "modules")
        export_chunks(chunks["tags"], vendor_output_dir, "tags")
        export_markdown(chunks["modules"], vendor_output_dir)

        LOGGER.info("[%s] Knowledge cases: %s", vendor, len(cases))
        LOGGER.info("[%s] New cases appended: %s", vendor, change_stats["new"])
        LOGGER.info("[%s] Existing cases replaced: %s", vendor, change_stats["changed"])
        LOGGER.info("[%s] Module chunks: %s", vendor, len(chunks["modules"]))
        LOGGER.info("[%s] Tag chunks: %s", vendor, len(chunks["tags"]))
        LOGGER.info("[%s] Potential duplicates: %s", vendor, len(chunks["duplicates"]))
        LOGGER.info("[%s] Output written to %s", vendor, vendor_output_dir)
    return 1 if failures else 0


def infer_vendor_name(xmind_path: Path) -> str:
    """Infer vendor folder name from the XMind file name."""
    name = xmind_path.stem
    name = re.sub(r"(?i)(_?test_?cases?|_?cases?)$", "", name).strip("_- ")
    return name or "Unknown_Vendor"


def load_existing_raw_stats(vendor_output_dir: Path, base_name: str) -> dict[str, Any] | None:
    raw_path = vendor_output_dir / "raw" / f"{base_name}_raw.json"
    if not raw_path.exists():
        return None
    try:
        with raw_path.open(encoding="utf-8") as file:
            return json.load(file).get("stats", {})
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Cannot read existing raw stats from %s: %s", raw_path, exc)
        return None


def load_existing_source_meta(vendor_output_dir: Path, base_name: str) -> dict[str, Any] | None:
    meta_path = vendor_output_dir / "source_meta" / f"{base_name}_source_meta.json"
    if not meta_path.exists():
        return None
    try:
        with meta_path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Cannot read existing source meta from %s: %s", meta_path, exc)
        return None


def processing_decision(
    current_stats: dict[str, Any],
    existing_stats: dict[str, Any] | None,
    current_meta: dict[str, Any] | None = None,
    existing_meta: dict[str, Any] | None = None,
) -> str:
    if not existing_stats:
        return "full"

    current_topics = int(current_stats.get("topic_count", 0))
    current_cases = int(current_stats.get("test_case_count", 0))
    existing_topics = int(existing_stats.get("topic_count", 0))
    existing_cases = int(existing_stats.get("test_case_count", 0))

    if current_topics == existing_topics and current_cases == existing_cases:
        if existing_meta and current_meta and current_meta.get("sha256") == existing_meta.get("sha256"):
            return "skip_equal"
        if not existing_meta:
            return "raw_only"
        return "raw_only"
    if current_topics < existing_topics or current_cases < existing_cases:
        return "preserve_decrease"
    if current_cases > existing_cases:
        return "incremental"
    return "raw_only"


def source_meta(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "source_file": path.name,
        "source_path": str(path),
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_existing_cases(vendor_output_dir: Path) -> list[dict[str, Any]]:
    modules_dir = vendor_output_dir / "modules"
    if not modules_dir.exists():
        return []

    cases_by_key: dict[str, dict[str, Any]] = {}
    for module_file in sorted(modules_dir.glob("*.json")):
        try:
            with module_file.open(encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.warning("Cannot read existing module chunk %s: %s", module_file, exc)
            continue

        for case in data.get("cases", []):
            key = case_identity(case)
            if key not in cases_by_key:
                cases_by_key[key] = case
    return list(cases_by_key.values())


def merge_existing_and_new_cases(
    existing_cases: list[dict[str, Any]], current_cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged_by_key = {case_identity(case): case for case in existing_cases}
    next_index = next_generated_index(existing_cases)

    for case in current_cases:
        key = case_identity(case)
        existing = merged_by_key.get(key)
        if existing and existing.get("content_hash") == case.get("content_hash"):
            continue
        if existing:
            case = dict(case)
            case["id"] = existing.get("id", case.get("id"))
            merged_by_key[key] = case
            continue
        if str(case.get("id", "")).startswith("TC_"):
            case = dict(case)
            case["id"] = f"TC_{next_index:04d}"
            next_index += 1
        merged_by_key[key] = case
    return list(merged_by_key.values())


def case_change_stats(
    existing_cases: list[dict[str, Any]], current_cases: list[dict[str, Any]]
) -> dict[str, int]:
    existing_by_key = {case_identity(case): case for case in existing_cases}
    new_count = 0
    changed_count = 0
    unchanged_count = 0
    for case in current_cases:
        existing = existing_by_key.get(case_identity(case))
        if not existing:
            new_count += 1
        elif existing.get("content_hash") == case.get("content_hash"):
            unchanged_count += 1
        else:
            changed_count += 1
    return {"new": new_count, "changed": changed_count, "unchanged": unchanged_count}


def case_identity(case: dict[str, Any]) -> str:
    source = case.get("source", {})
    topic_id = source.get("topic_id")
    if topic_id:
        return f"topic:{topic_id}"
    return "|".join(
        [
            str(source.get("xmind_file", "")),
            str(case.get("module", "")),
            str(case.get("scenario", "")),
            str(case.get("path", "")),
        ]
    )


def next_generated_index(cases: list[dict[str, Any]]) -> int:
    max_index = 0
    for case in cases:
        match = re.match(r"TC_(\d+)$", str(case.get("id", "")))
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def build_vendor_report(cases: list[dict[str, Any]], parsed_files: list[dict[str, Any]]) -> dict[str, Any]:
    module_counts = Counter(case.get("module", "unclassified") for case in cases)
    tag_counts = Counter(tag for case in cases for tag in case.get("tags", []))
    raw_files = sorted(
        {
            str(case.get("source", {}).get("xmind_file", ""))
            for case in cases
            if case.get("source", {}).get("xmind_file")
        }
    )
    parsed_files_by_name = {item.get("source_file", ""): item for item in parsed_files}

    return {
        "files_opened": raw_files or sorted(parsed_files_by_name),
        "total_files": len(raw_files or parsed_files_by_name),
        "total_sheets": sum(item.get("stats", {}).get("sheet_count", 0) for item in parsed_files),
        "total_topics": sum(item.get("stats", {}).get("topic_count", 0) for item in parsed_files),
        "total_cases": len(cases),
        "total_modules": len(module_counts),
        "total_tags": len(tag_counts),
        "modules": dict(sorted(module_counts.items())),
        "tags": dict(sorted(tag_counts.items())),
        "fields_attempted": [
            "api_name",
            "scenario",
            "preconditions",
            "steps",
            "expected_results",
            "validation_points",
            "db_checks",
            "tags",
            "parent_topic",
            "child_topic",
            "hierarchy_path",
        ],
    }


def resolve_input_files(
    input_value: str | None, default_input_dir: Path, output_dir: Path
) -> list[Path] | None:
    """Resolve CLI input into concrete XMind files."""
    if input_value is None:
        if not default_input_dir.exists():
            LOGGER.error("Input folder does not exist: %s", default_input_dir)
            return None
        return sorted(default_input_dir.glob("*.xmind"))

    target = Path(input_value)
    candidates = [target]
    if not target.is_absolute():
        candidates.append(default_input_dir / input_value)

    existing = next((candidate for candidate in candidates if candidate.exists()), None)
    if existing is None:
        if target.suffix.lower() == ".xmind":
            LOGGER.error("XMind file does not exist: %s", input_value)
        else:
            LOGGER.error("Input path does not exist: %s", input_value)
        if default_input_dir.exists():
            print_available_files(sorted(default_input_dir.glob("*.xmind")), output_dir)
        return None

    if existing.is_file():
        if existing.suffix.lower() != ".xmind":
            LOGGER.error("Unsupported input file extension: %s", existing)
            return None
        return [existing]

    if existing.is_dir():
        return sorted(existing.glob("*.xmind"))

    LOGGER.error("Unsupported input path: %s", existing)
    return None


def print_available_files(files: list[Path], output_dir: Path) -> None:
    """Show available XMind files with processed status."""
    print("Available XMind files:")
    for file_path in files:
        vendor = normalize_vendor_name(infer_vendor_name(file_path))
        status = "processed" if is_processed(file_path, output_dir, vendor) else "not processed"
        print(f"  - {file_path.name} [{vendor}] {status}")


def is_processed(xmind_path: Path, output_dir: Path, vendor: str) -> bool:
    raw_path = output_dir / vendor / "raw" / f"{xmind_path.stem}_raw.json"
    return raw_path.exists()


def normalize_vendor_name(value: str) -> str:
    """Make a stable vendor folder name for Windows paths and JSON output."""
    name = value.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_-")
    return name or "Unknown_Vendor"


if __name__ == "__main__":
    raise SystemExit(main())
