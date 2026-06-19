"""Export supplementary URL reader outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_validation_report(validation: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "validation_report.json"
    _write_json(path, validation)
    return path


def export_full_text(markdown: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "full_text.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def export_endpoint_index(endpoint_index: list[dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    public_index = [{key: value for key, value in item.items() if key != "line_index"} for item in endpoint_index]
    path = output_dir / "endpoint_index.json"
    _write_json(path, public_index)
    return path


def export_sections(sections: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    sections_dir = output_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    for old_file in sections_dir.glob("*.json"):
        old_file.unlink()
    paths = []
    used_names: dict[str, int] = {}
    for section in sections:
        path = sections_dir / _section_filename(section, used_names)
        _write_json(path, section)
        paths.append(path)
    return paths


def export_manifest(
    vendor: str,
    source_url: str,
    final_url: str,
    validation: dict[str, Any],
    endpoint_count: int,
    section_count: int,
    output_dir: Path,
) -> Path:
    manifest = {
        "vendor": vendor,
        "source_url": source_url,
        "final_url": final_url,
        "reader": "url_reader",
        "readable": validation.get("readable", False),
        "requires_auth": validation.get("requires_auth", False),
        "content_type": validation.get("content_type", ""),
        "content_sha256": validation.get("content_sha256", ""),
        "fetch_method": validation.get("fetch_method", ""),
        "total_sections": section_count,
        "total_endpoints": endpoint_count,
        "files": {
            "validation_report": "validation_report.json",
            "endpoint_index": "endpoint_index.json" if endpoint_count else "",
            "full_text": "full_text.md" if validation.get("readable") else "",
            "sections_dir": "sections/" if section_count else "",
        },
        "usage_note": "URL reader output is supplementary. Main source is DOC/HTML reader output.",
    }
    path = output_dir / "manifest.json"
    _write_json(path, manifest)
    return path


def clean_extracted_outputs(output_dir: Path) -> None:
    for file_name in ("endpoint_index.json", "full_text.md"):
        path = output_dir / file_name
        if path.exists():
            path.unlink()
    sections_dir = output_dir / "sections"
    if sections_dir.exists():
        for section_file in sections_dir.glob("*.json"):
            section_file.unlink()


def _section_filename(section: dict[str, Any], used_names: dict[str, int]) -> str:
    raw = section.get("api_name") or section.get("endpoint") or section.get("section_id") or "api_section"
    slug = "".join(char.lower() if char.isalnum() else "_" for char in raw)
    slug = "_".join(part for part in slug.split("_") if part)
    slug = slug or "api_section"
    count = used_names.get(slug, 0) + 1
    used_names[slug] = count
    if count > 1:
        slug = f"{slug}_{count}"
    return f"{slug}.json"


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
