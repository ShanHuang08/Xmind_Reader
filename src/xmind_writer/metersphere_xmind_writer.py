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
from generator.user_behavior_mapping import (
    BET_AND_SETTLE_CONFIG_SECTION,
    BET_SETTLE_GAME_CATEGORY,
    GAME_CATEGORY_MODULES,
)


def write_xmind_from_draft(
    draft: dict[str, Any], output_path: Path | str, show_case_id: bool = False
) -> Path:
    """Validate a draft object and write it as an XMind archive."""
    result = validate_draft(draft)
    if not result.valid:
        messages = "; ".join(f"{issue.path}: {issue.message}" for issue in result.errors)
        raise ValueError(f"Draft failed validation before XMind writing: {messages}")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = [_build_sheet(draft, show_case_id=show_case_id)]
    metadata = _metadata(draft)
    manifest = _manifest()

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.json", json.dumps(content, ensure_ascii=False, indent=2))
        archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return output


def write_no_merge_key_copy(xmind_path: Path | str, output_path: Path | str | None = None) -> Path:
    """Write a delivery copy with visible merge_key topics removed."""
    source = Path(xmind_path)
    target = Path(output_path) if output_path else source.with_name(f"{source.stem}_no_merge_key{source.suffix}")

    with zipfile.ZipFile(source, "r") as input_archive:
        entries = []
        for info in input_archive.infolist():
            data = input_archive.read(info.filename)
            if info.filename == "content.json":
                content = json.loads(data.decode("utf-8"))
                for sheet in content if isinstance(content, list) else [content]:
                    root = sheet.get("rootTopic") if isinstance(sheet, dict) else None
                    if isinstance(root, dict):
                        _remove_merge_key_topics(root)
                data = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
            entries.append((info, data))

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as output_archive:
        for info, data in entries:
            output_archive.writestr(info, data)
    return target


def _remove_merge_key_topics(topic: dict[str, Any]) -> None:
    children = topic.get("children")
    if not isinstance(children, dict):
        return
    attached = children.get("attached")
    if not isinstance(attached, list):
        return
    kept = []
    for child in attached:
        if not isinstance(child, dict):
            kept.append(child)
            continue
        if str(child.get("title", "")).startswith("merge_key:"):
            continue
        _remove_merge_key_topics(child)
        kept.append(child)
    children["attached"] = kept


def _build_sheet(draft: dict[str, Any], show_case_id: bool = False) -> dict[str, Any]:
    vendor = draft.get("vendor") or "GeneratedVendor"
    root = _topic("功能用例")
    regression = _ensure_child(root, "Regression")
    vendor_integration = _ensure_child(regression, "Vendor_integration")
    vendor_topic = _ensure_child(vendor_integration, vendor)
    test_cases = draft.get("test_cases", [])
    _ensure_fixed_user_behavior_categories(vendor_topic, test_cases)

    for case in test_cases:
        if not isinstance(case, dict):
            continue
        _place_case(vendor_topic, case, show_case_id=show_case_id)

    return {
        "id": _id(),
        "class": "sheet",
        "title": vendor,
        "rootTopic": root,
    }


def _ensure_fixed_user_behavior_categories(
    vendor_topic: dict[str, Any], test_cases: Any = None
) -> None:
    """Create fixed branches, omitting an empty BetAndSettle config branch."""
    user_behavior = _ensure_child(vendor_topic, "User Behavior")
    bet_and_settle = _ensure_child(user_behavior, "Bet and Settle")
    game_type = _ensure_child(bet_and_settle, "Game type")
    selected_game_categories = _selected_game_category_titles(test_cases)
    if selected_game_categories:
        game_category = _ensure_child(game_type, "Game category")
        for title in selected_game_categories:
            _ensure_child(game_category, title)
    _ensure_child(game_type, "Main flow")
    bet_and_settle_children = ["Bet config", "Settle config"]
    if _has_bet_and_settle_config_cases(test_cases):
        bet_and_settle_children.append("BetAndSettle config")
    bet_and_settle_children.extend(["Special accounts", "Player / Game status"])
    for title in bet_and_settle_children:
        _ensure_child(bet_and_settle, title)
    cancel_bet = _ensure_child(user_behavior, "Cancel Bet")
    for title in (
        "Main flow",
        "Cancel config",
        "Special accounts",
        "Player / Game status",
    ):
        _ensure_child(cancel_bet, title)


def _has_bet_and_settle_config_cases(test_cases: Any) -> bool:
    if not isinstance(test_cases, list):
        return False
    return any(
        isinstance(case, dict)
        and (
            str(case.get("output_section", "")) == BET_AND_SETTLE_CONFIG_SECTION
            or str(case.get("output_section", "")).endswith(
                " > BetAndSettle config"
            )
        )
        for case in test_cases
    )


def _selected_game_category_titles(test_cases: Any) -> list[str]:
    """Return only Game category branches that contain generated cases."""
    if not isinstance(test_cases, list):
        return []
    prefix = f"{BET_SETTLE_GAME_CATEGORY} > "
    selected = {
        str(case.get("output_section", ""))[len(prefix) :].strip()
        for case in test_cases
        if isinstance(case, dict)
        and str(case.get("output_section", "")).startswith(prefix)
    }
    return [title for title in GAME_CATEGORY_MODULES.values() if title in selected]


def _place_case(vendor_topic: dict[str, Any], case: dict[str, Any], show_case_id: bool = False) -> None:
    output_section = case.get("output_section", "")
    if output_section == API_PARAMETER_TEST_SECTION:
        section = _ensure_child(vendor_topic, API_PARAMETER_TEST_SECTION)
        endpoint = _ensure_child(section, _endpoint_display_name(case))
        _append_case_topic(endpoint, case, show_case_id=show_case_id)
        return

    parent = vendor_topic
    for part in [part.strip() for part in output_section.split(">") if part.strip()]:
        parent = _ensure_child(parent, part)
    _append_case_topic(parent, case, show_case_id=show_case_id)


def _append_case_topic(parent: dict[str, Any], case: dict[str, Any], show_case_id: bool = False) -> None:
    scenario = str(case.get("scenario") or "未命名用例")
    title = scenario if scenario.startswith(CASE_TITLE_PREFIX) else f"{CASE_TITLE_PREFIX}{scenario}"
    case_topic = _topic(title)
    markers = _case_markers(case)
    if markers:
        case_topic["markers"] = [{"markerId": marker_id} for marker_id in markers]
    case_topic["children"] = {"attached": _case_field_topics(case, show_case_id=show_case_id)}
    _children(parent).append(case_topic)


def _case_field_topics(case: dict[str, Any], show_case_id: bool = False) -> list[dict[str, Any]]:
    labels = XMIND_CASE_FIELD_LABELS
    topics = [
        _topic(str(case.get("preconditions", f"{labels['preconditions']}"))),
        _topic(f"{labels['module']}{case.get('module') or _module_from_case(case)}"),
        _topic(f"{labels['labels']}{', '.join(case.get('tags', []))}"),
        _topic(str(case.get("remarks", f"{labels['remarks']}"))),
        _topic(f"{labels['priority']}{case.get('priority', 'P2')}"),
        _steps_topic(case),
    ]
    stable_case_id = str(case.get("stable_case_id") or case.get("id") or "").strip()
    if stable_case_id:
        topics.insert(0, _topic(f"merge_key:{stable_case_id}"))
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


def _case_markers(case: dict[str, Any]) -> list[str]:
    markers = case.get("markers", [])
    if not isinstance(markers, list):
        return []
    output = []
    for marker in markers:
        marker_id = str(marker).strip()
        if marker_id and marker_id not in output:
            output.append(marker_id)
    return output


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
