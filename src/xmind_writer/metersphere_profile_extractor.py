"""Extract a lightweight MeterSphere-compatible XMind profile from golden files."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from parser.xmind_reader import parse_xmind_file


def extract_metersphere_profile(
    input_xmind_root: Path | str = "input_xmind",
    output_path: Path | str = "xmind_detail/_metersphere_profile/metersphere_schema_profile.json",
) -> Path:
    root = Path(input_xmind_root)
    files = sorted(root.glob("*.xmind"))
    parsed_files = [parse_xmind_file(path) for path in files]
    profile = build_profile(parsed_files)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_profile(parsed_files: list[dict[str, Any]]) -> dict[str, Any]:
    case_field_counter: Counter[str] = Counter()
    root_titles: Counter[str] = Counter()
    sheet_titles: Counter[str] = Counter()
    example_paths: list[list[str]] = []
    max_depth = 0

    for parsed in parsed_files:
        for sheet in parsed.get("sheets", []):
            sheet_titles.update([sheet.get("title", "")])
            root = sheet.get("root_topic", {})
            root_titles.update([root.get("title", "")])
            for topic in _walk(root):
                path = topic.get("path", [])
                max_depth = max(max_depth, len(path))
                if str(topic.get("title", "")).startswith(("case：", "case:")):
                    if len(example_paths) < 20:
                        example_paths.append(path)
                    for child in topic.get("children", []):
                        title = str(child.get("title", ""))
                        field = title.split("：", 1)[0].split(":", 1)[0]
                        if field:
                            case_field_counter.update([field])

    return {
        "profile_version": "metersphere-xmind-profile/v1",
        "source_files": [parsed.get("source_file", "") for parsed in parsed_files],
        "supported_source_formats": sorted(
            {parsed.get("source_format", "") for parsed in parsed_files if parsed.get("source_format")}
        ),
        "sheet_titles": dict(sheet_titles),
        "root_topic_titles": dict(root_titles),
        "case_field_labels": dict(case_field_counter),
        "maximum_observed_depth": max_depth,
        "example_case_paths": example_paths,
        "writer_guidance": {
            "case_topic_prefix": "case：",
            "steps_root": "步骤描述",
            "step_prefix": "步骤：",
            "expected_prefix": "预期结果：",
            "preferred_case_fields": [
                "前置条件",
                "所属模块",
                "标签",
                "备注",
                "用例等级",
                "步骤描述",
            ],
        },
    }


def _walk(topic: dict[str, Any]):
    if not topic:
        return
    yield topic
    for child in topic.get("children", []):
        yield from _walk(child)
