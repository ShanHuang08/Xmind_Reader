"""JSON exporters for raw, summary, module, and tag outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(data: Any, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def export_raw(parsed: dict[str, Any], output_dir: Path, base_name: str) -> Path:
    return write_json(parsed, Path(output_dir) / "raw" / f"{base_name}_raw.json")


def export_source_meta(meta: dict[str, Any], output_dir: Path, base_name: str) -> Path:
    return write_json(meta, Path(output_dir) / "source_meta" / f"{base_name}_source_meta.json")


def export_summary(report: dict[str, Any], output_dir: Path, name: str = "summary.json") -> Path:
    summary = {
        "total_cases": report.get("total_cases", 0),
        "total_modules": report.get("total_modules", 0),
        "total_tags": report.get("total_tags", 0),
        "modules": report.get("modules", {}),
        "tags": report.get("tags", {}),
        "files": report.get("files_opened", []),
    }
    return write_json(summary, Path(output_dir) / "summary" / name)


def export_extraction_report(
    report: dict[str, Any], duplicates: list[dict[str, Any]], output_dir: Path
) -> Path:
    data = dict(report)
    data["duplicate_count"] = len(duplicates)
    return write_json(data, Path(output_dir) / "summary" / "extraction_report.json")


def export_duplicate_report(duplicates: list[dict[str, Any]], output_dir: Path) -> Path:
    return write_json(
        {"duplicate_count": len(duplicates), "duplicates": duplicates},
        Path(output_dir) / "summary" / "duplicate_report.json",
    )


def export_chunks(chunks: dict[str, list[dict[str, Any]]], output_dir: Path, folder: str) -> list[Path]:
    paths = []
    for chunk_name, cases in chunks.items():
        paths.append(
            write_json(
                {
                    "chunk": chunk_name,
                    "total_cases": len(cases),
                    "cases": [_compact_case(case) for case in cases],
                },
                Path(output_dir) / folder / f"{chunk_name}.json",
            )
        )
    return paths


def _compact_case(case: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "id",
        "duplicate_of",
        "api_name",
        "module",
        "scenario",
        "path",
        "level",
        "parent_topic",
        "child_topic",
        "preconditions",
        "steps",
        "expected_results",
        "validation_points",
        "db_checks",
        "tags",
        "priority",
        "content_hash",
        "source",
    ]
    return {key: case[key] for key in keep if case.get(key) not in ("", None, [], {})}
