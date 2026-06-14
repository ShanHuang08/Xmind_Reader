"""Markdown knowledge exporter."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


def export_markdown(module_chunks: dict[str, list[dict[str, Any]]], output_dir: Path) -> list[Path]:
    paths = []
    base = Path(output_dir) / "markdown"
    base.mkdir(parents=True, exist_ok=True)
    for chunk_name, cases in module_chunks.items():
        module_name = cases[0].get("module", chunk_name) if cases else chunk_name
        path = base / f"{chunk_name}.md"
        path.write_text(_render_module(module_name, cases), encoding="utf-8")
        paths.append(path)
    return paths


def _render_module(module_name: str, cases: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        primary = _primary_tag(case.get("tags", []))
        grouped[primary].append(case)

    lines = [f"# {module_name}", ""]
    for tag in sorted(grouped):
        lines.extend([f"## {tag}", ""])
        for case in grouped[tag]:
            lines.append(f"* {case.get('id')} {case.get('scenario', '')}")
            checks = case.get("validation_points", [])[:5]
            db_checks = case.get("db_checks", [])[:5]
            if checks:
                lines.append("  Checks:")
                lines.extend(f"  * {item}" for item in checks)
            if db_checks:
                lines.append("  DB Checks:")
                lines.extend(f"  * {item}" for item in db_checks)
            if case.get("duplicate_of"):
                lines.append(f"  Duplicate of: {case['duplicate_of']}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _primary_tag(tags: list[str]) -> str:
    for preferred in (
        "idempotency",
        "rollback",
        "boundary",
        "validation",
        "timeout",
        "negative",
        "positive",
    ):
        if preferred in tags:
            return preferred
    return tags[0] if tags else "unclassified"
