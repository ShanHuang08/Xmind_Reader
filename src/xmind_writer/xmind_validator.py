"""Validate generated XMind files by reading them back."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from parser.xmind_reader import parse_xmind_file


def validate_generated_xmind(
    xmind_path: Path | str,
    draft: dict[str, Any],
    report_path: Path | str | None = None,
) -> dict[str, Any]:
    parsed = parse_xmind_file(Path(xmind_path))
    parsed_cases = parsed.get("source_cases", [])
    draft_cases = [case for case in draft.get("test_cases", []) if isinstance(case, dict)]

    errors: list[str] = []
    warnings: list[str] = []
    if len(parsed_cases) != len(draft_cases):
        errors.append(
            f"Case count mismatch: draft has {len(draft_cases)}, generated XMind has {len(parsed_cases)}."
        )

    draft_scenarios = {str(case.get("scenario", "")).replace("case：", "").strip() for case in draft_cases}
    parsed_names = {str(case.get("name", "")).strip() for case in parsed_cases}
    missing = sorted(name for name in draft_scenarios if name and name not in parsed_names)
    if missing:
        errors.append(f"Missing parsed case scenario(s): {missing[:10]}")

    api_cases = [case for case in draft_cases if case.get("output_section") == "API parameter test"]
    if api_cases and not _has_topic_path(parsed, "API parameter test"):
        errors.append("Generated XMind is missing API parameter test hierarchy.")

    report = {
        "valid": not errors,
        "xmind_path": str(xmind_path),
        "draft_case_count": len(draft_cases),
        "parsed_case_count": len(parsed_cases),
        "errors": errors,
        "warnings": warnings,
        "parser_stats": parsed.get("stats", {}),
    }
    if report_path:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _has_topic_path(parsed: dict[str, Any], title: str) -> bool:
    for sheet in parsed.get("sheets", []):
        for topic in _walk(sheet.get("root_topic", {})):
            if topic.get("title") == title:
                return True
    return False


def _walk(topic: dict[str, Any]):
    if not topic:
        return
    yield topic
    for child in topic.get("children", []):
        yield from _walk(child)
