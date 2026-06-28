"""Write MeterSphere-style XMind files from validated draft cases."""

from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

from generator.draft_schema import (
    API_PARAMETER_TEST_SECTION,
    CASE_TITLE_PREFIX,
    XMIND_CASE_FIELD_LABELS,
)
from generator.draft_validator import validate_draft


def write_xmind_from_draft(draft: dict[str, Any], output_path: Path | str) -> Path:
    """Validate a draft object and write it as an XMind archive."""
    result = validate_draft(draft)
    if not result.valid:
        messages = "; ".join(f"{issue.path}: {issue.message}" for issue in result.errors)
        raise ValueError(f"Draft failed validation before XMind writing: {messages}")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = [_build_sheet(draft)]
    metadata = _metadata(draft)
    manifest = _manifest()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.json", json.dumps(content, ensure_ascii=False, indent=2))
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return output


def _build_sheet(draft: dict[str, Any]) -> dict[str, Any]:
    vendor = draft.get("vendor") or "GeneratedVendor"
    root = _topic("功能用例")
    regression = _ensure_child(root, "Regression")
    vendor_integration = _ensure_child(regression, "Vendor_integration")
    vendor_topic = _ensure_child(vendor_integration, vendor)

    for case in draft.get("test_cases", []):
        if not isinstance(case, dict):
            continue
        _place_case(vendor_topic, case)

    return {
        "id": _id(),
        "class": "sheet",
        "title": vendor,
        "rootTopic": root,
    }


def _place_case(vendor_topic: dict[str, Any], case: dict[str, Any]) -> None:
    output_section = case.get("output_section", "")
    if output_section == API_PARAMETER_TEST_SECTION:
        section = _ensure_child(vendor_topic, API_PARAMETER_TEST_SECTION)
        endpoint = _ensure_child(section, _endpoint_display_name(case))
        _append_case_topic(endpoint, case)
        return

    parent = vendor_topic
    for part in [part.strip() for part in output_section.split(">") if part.strip()]:
        parent = _ensure_child(parent, part)
    _append_case_topic(parent, case)


def _append_case_topic(parent: dict[str, Any], case: dict[str, Any]) -> None:
    scenario = str(case.get("scenario") or "未命名用例")
    title = scenario if scenario.startswith(CASE_TITLE_PREFIX) else f"{CASE_TITLE_PREFIX}{scenario}"
    case_topic = _topic(title)
    case_topic["children"] = {"attached": _case_field_topics(case)}
    _children(parent).append(case_topic)


def _case_field_topics(case: dict[str, Any]) -> list[dict[str, Any]]:
    labels = XMIND_CASE_FIELD_LABELS
    topics = [
        _topic(str(case.get("preconditions", f"{labels['preconditions']}"))),
        _topic(f"{labels['module']}{case.get('module') or _module_from_case(case)}"),
        _topic(f"{labels['labels']}{', '.join(case.get('tags', []))}"),
        _topic(str(case.get("remarks", f"{labels['remarks']}"))),
        _topic(f"{labels['priority']}{case.get('priority', 'P2')}"),
        _steps_topic(case),
    ]
    if case.get("id"):
        topics.insert(0, _topic(f"ID：{case.get('id')}"))
    return topics


def _steps_topic(case: dict[str, Any]) -> dict[str, Any]:
    labels = XMIND_CASE_FIELD_LABELS
    root = _topic(labels["steps_root"].rstrip("："))
    step_topics = []
    for index, step in enumerate(case.get("steps", []), start=1):
        if not isinstance(step, dict):
            continue
        step_title = f"{labels['step'].format(index=index)}{step.get('step', '')}"
        step_topic = _topic(step_title)
        expected_title = f"{labels['expected']}{step.get('expected', '')}"
        step_topic["children"] = {"attached": [_topic(expected_title)]}
        step_topics.append(step_topic)
    root["children"] = {"attached": step_topics}
    return root


def _module_from_case(case: dict[str, Any]) -> str:
    if case.get("output_section") == API_PARAMETER_TEST_SECTION:
        return _endpoint_display_name(case)
    output_section = str(case.get("output_section", ""))
    return output_section.split(">")[-1].strip() if output_section else "未分类模块"


def _endpoint_display_name(case: dict[str, Any]) -> str:
    endpoint_name = str(case.get("endpoint_name", "")).strip()
    if endpoint_name:
        return endpoint_name
    endpoint = str(case.get("endpoint", "")).strip().rstrip("/")
    if endpoint:
        return endpoint.rsplit("/", 1)[-1] or endpoint
    return "未分类接口"


def _ensure_child(parent: dict[str, Any], title: str) -> dict[str, Any]:
    children = _children(parent)
    for child in children:
        if child.get("title") == title:
            return child
    child = _topic(title)
    children.append(child)
    return child


def _children(topic: dict[str, Any]) -> list[dict[str, Any]]:
    children = topic.setdefault("children", {}).setdefault("attached", [])
    return children


def _topic(title: str) -> dict[str, Any]:
    return {
        "id": _id(),
        "class": "topic",
        "title": title,
    }


def _metadata(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataStructureVersion": "3",
        "creator": {
            "name": "Xmind_Reader generator",
            "version": "1.0.0",
        },
        "layoutEngineVersion": "5",
        "vendor": draft.get("vendor", ""),
        "schema_version": draft.get("schema_version", ""),
    }


def _manifest() -> dict[str, Any]:
    return {
        "file-entries": {
            "content.json": {},
            "metadata.json": {},
        }
    }


def _id() -> str:
    return str(uuid.uuid4())
