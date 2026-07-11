"""Merge human-edited XMind cases back into generated draft cases."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from generator.draft_schema import (
    API_PARAMETER_TEST_SECTION,
    CASE_TITLE_PREFIX,
    PRECONDITIONS_LABEL,
    REMARKS_LABEL,
)
from parser.xmind_reader import parse_xmind_file


HUMAN_OVERLAY_GENERATED_BY = "human-xmind-overlay/v1"


def ensure_stable_case_ids(draft: dict[str, Any]) -> dict[str, Any]:
    """Ensure every draft test case has a deterministic stable_case_id."""
    for case in draft.get("test_cases", []) or []:
        if isinstance(case, dict):
            case.setdefault("stable_case_id", stable_case_key(case))
    return draft


def stable_case_key(case: dict[str, Any]) -> str:
    stable = str(case.get("stable_case_id", "")).strip()
    if stable:
        return stable

    category = str(case.get("category", "")).strip()
    endpoint = str(case.get("endpoint", "")).strip()
    parameter = str(case.get("parameter", "")).strip()
    if category == "parameter_validation" or case.get("output_section") == API_PARAMETER_TEST_SECTION:
        return f"param::{_slug(endpoint)}::{_slug(parameter)}"

    source_reference = case.get("source_reference") if isinstance(case.get("source_reference"), dict) else {}
    generated_by = str(source_reference.get("generated_by", ""))
    if generated_by == HUMAN_OVERLAY_GENERATED_BY or category == "human_added":
        return _human_case_key(case)

    source_id = str(source_reference.get("source_case_id", "")).strip()
    if source_id:
        return f"ub::{_slug(category or _module_key(case))}::{_slug(source_id)}"
    source_path = str(source_reference.get("source_path", "")).strip()
    if source_path:
        seed = "|".join([source_path, category, str(case.get("scenario", ""))])
        return f"ub::{_slug(category or _module_key(case))}::source_{_short_hash(seed)}"

    return _human_case_key(case)


def merge_human_xmind_edits(
    draft: dict[str, Any],
    human_xmind_path: Path,
    report_md_path: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Apply human-edited scenario/steps overlays from an XMind copy."""
    ensure_stable_case_ids(draft)
    base_cases = [case for case in draft.get("test_cases", []) if isinstance(case, dict)]
    human_cases = _human_draft_cases(Path(human_xmind_path))
    _normalize_human_added_remarks(human_cases, draft)
    previous_manifest = _load_manifest(manifest_path)
    previous_keys = set(previous_manifest.get("final_case_keys", [])) if previous_manifest else set()
    manifest_missing = manifest_path is not None and not previous_manifest

    human_index, duplicate_same_title, regenerated_human_ids = _human_case_index(human_cases)
    used_human_keys: set[str] = set()

    final_cases: list[dict[str, Any]] = []
    overridden: list[dict[str, Any]] = []
    deleted_by_human: list[dict[str, Any]] = []
    new_from_base: list[dict[str, Any]] = []
    base_only_without_manifest: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    if manifest_missing:
        warnings.append(
            {
                "code": "manifest_missing",
                "message": "Previous manifest is missing. Base-only cases are kept.",
            }
        )

    for base_case in base_cases:
        human_case = _matching_human_case(base_case, human_index)
        if human_case:
            used_human_keys.add(stable_case_key(human_case))
            merged_case, fields, field_warnings = _overlay_human_case(base_case, human_case)
            final_cases.append(merged_case)
            warnings.extend(field_warnings)
            if fields:
                overridden.append(
                    {
                        "stable_case_id": stable_case_key(merged_case),
                        "fields": fields,
                    }
                )
            continue

        base_key = stable_case_key(base_case)
        if previous_manifest:
            if base_key in previous_keys:
                deleted_by_human.append(
                    {
                        "stable_case_id": base_key,
                        "scenario": str(base_case.get("scenario", "")),
                    }
                )
                continue
            new_from_base.append(
                {
                    "stable_case_id": base_key,
                    "scenario": str(base_case.get("scenario", "")),
                }
            )
        else:
            base_only_without_manifest.append(
                {
                    "stable_case_id": base_key,
                    "scenario": str(base_case.get("scenario", "")),
                }
            )
        final_cases.append(base_case)

    added_from_human: list[dict[str, str]] = []
    for human_case in human_cases:
        if human_case.get("_skip_human_duplicate"):
            continue
        human_key = stable_case_key(human_case)
        if human_key in used_human_keys:
            continue
        final_cases.append(human_case)
        added_from_human.append(
            {
                "stable_case_id": human_key,
                "scenario": str(human_case.get("scenario", "")),
            }
        )

    conflicts: list[dict[str, str]] = []

    draft["test_cases"] = final_cases
    report = {
        "status": "success" if not conflicts else "warning",
        "summary": {
            "base_cases": len(base_cases),
            "human_cases": len(human_cases),
            "overridden": len(overridden),
            "added_from_human": len(added_from_human),
            "deleted_by_human": len(deleted_by_human),
            "new_from_base": len(new_from_base),
            "base_only_without_manifest": len(base_only_without_manifest),
            "regenerated_human_ids": len(regenerated_human_ids),
            "duplicate_same_title": len(duplicate_same_title),
            "warnings": len(warnings),
            "conflicts": len(conflicts),
        },
        "overridden": overridden,
        "added_from_human": added_from_human,
        "deleted_by_human": deleted_by_human,
        "regenerated_human_ids": regenerated_human_ids,
        "duplicate_same_title": duplicate_same_title,
        "warnings": warnings,
        "conflicts": conflicts,
    }
    _write_merge_report(report_md_path, str(draft.get("vendor", "")), report)
    return draft


def _normalize_human_added_remarks(human_cases: list[dict[str, Any]], draft: dict[str, Any]) -> None:
    for case in human_cases:
        if not (_needs_non_launch_remarks_fix(case) or _needs_api_payload_remarks_refresh(case)):
            continue
        endpoints = _endpoints_for_human_case(case, draft)
        if endpoints:
            case["remarks"] = _multi_endpoint_remarks(endpoints)
        else:
            case["remarks"] = (
                f"{REMARKS_LABEL}\n"
                "API request parameters need to be filled from the target vendor endpoint. "
                "Do not reuse the launch-game /game/url payload for this case."
            )


def _needs_non_launch_remarks_fix(case: dict[str, Any]) -> bool:
    output_section = str(case.get("output_section", ""))
    if output_section == "User Behavior > Launch Game":
        return False
    remarks = str(case.get("remarks", ""))
    return "gameCode" in remarks and "lobbyUrl" in remarks and "ipAddress" in remarks


def _needs_api_payload_remarks_refresh(case: dict[str, Any]) -> bool:
    remarks = str(case.get("remarks", ""))
    if "API request parameters" not in remarks or "Success response" not in remarks:
        return False
    stale_tokens = (
        "20110322T152403Z",
        '"result": "ERROR"',
        "sample_",
        "Error response",
    )
    return any(token in remarks for token in stale_tokens)


def _endpoints_for_human_case(
    case: dict[str, Any], draft: dict[str, Any]
) -> list[dict[str, Any]]:
    endpoints = [item for item in draft.get("endpoint_roles", []) if isinstance(item, dict)]
    by_role: dict[str, list[dict[str, Any]]] = {}
    for endpoint in endpoints:
        by_role.setdefault(str(endpoint.get("role", "")), []).append(endpoint)

    output_section = str(case.get("output_section", ""))
    text = _case_search_text(case)
    if "Get Player balance" in output_section:
        return by_role.get("balance_check", [])
    if "Cancel Bet" in output_section:
        return by_role.get("cancel_bet", []) or by_role.get("rollback", [])
    if "Bet and Settle" in output_section:
        if _mentions_cancel(text):
            return by_role.get("cancel_bet", []) or by_role.get("rollback", [])
        if _mentions_settlement(text) and _mentions_bet(text):
            return (by_role.get("bet", [])[:1] + by_role.get("settlement", [])[:1])
        if _mentions_settlement(text):
            return by_role.get("settlement", [])
        if _mentions_bet(text):
            return by_role.get("bet", [])
        return by_role.get("bet", [])[:1] + by_role.get("settlement", [])[:1]
    return []


def _case_search_text(case: dict[str, Any]) -> str:
    parts = [
        str(case.get("scenario", "")),
        str(case.get("module", "")),
        str(case.get("output_section", "")),
    ]
    for step in case.get("steps", []) if isinstance(case.get("steps"), list) else []:
        if isinstance(step, dict):
            parts.append(str(step.get("step", "")))
            parts.append(str(step.get("expected", "")))
    return " ".join(parts).lower()


def _mentions_cancel(text: str) -> bool:
    return any(term in text for term in ("cancel", "refund", "rollback"))


def _mentions_settlement(text: str) -> bool:
    return any(term in text for term in ("settle", "settlement", "win", "endround", "end round"))


def _mentions_bet(text: str) -> bool:
    return any(term in text for term in ("bet", "freespin", "free spin", "insufficient fund"))


def _multi_endpoint_remarks(endpoints: list[dict[str, Any]]) -> str:
    sections = [f"{REMARKS_LABEL}"]
    for endpoint in endpoints:
        endpoint_path = str(endpoint.get("endpoint", "target endpoint"))
        request = _json_payload(endpoint.get("request_example"))
        response = _json_payload(endpoint.get("success_response_example"))
        sections.extend(
            [
                f"Endpoint: {endpoint_path}",
                "API request parameters:",
                "<code>",
                request,
                "</code>",
                "Success response:",
                "<code>",
                response,
                "</code>",
            ]
        )
    return "\n".join(sections)


def _json_payload(value: Any) -> str:
    if isinstance(value, dict) and value:
        return json.dumps(value, ensure_ascii=False, indent=2)
    return "{}"


def write_human_merge_manifest(draft: dict[str, Any], manifest_path: Path | str) -> Path:
    """Write the manifest used to detect future human deletions."""
    ensure_stable_case_ids(draft)
    path = Path(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    case_index = {}
    final_case_keys = []
    for case in draft.get("test_cases", []) or []:
        if not isinstance(case, dict):
            continue
        key = stable_case_key(case)
        final_case_keys.append(key)
        case_index[key] = {
            "scenario": str(case.get("scenario", "")),
            "output_section": str(case.get("output_section", "")),
            "module": str(case.get("module", "")),
        }
    payload = {
        "vendor": draft.get("vendor", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "final_case_keys": final_case_keys,
        "case_index": case_index,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _human_draft_cases(human_xmind_path: Path) -> list[dict[str, Any]]:
    parsed = parse_xmind_file(human_xmind_path)
    output = []
    for source_case in parsed.get("source_cases", []):
        if isinstance(source_case, dict):
            output.append(_source_case_to_draft_case(source_case, human_xmind_path))
    return output


def _source_case_to_draft_case(source_case: dict[str, Any], human_xmind_path: Path) -> dict[str, Any]:
    scenario = _scenario_from_source_name(str(source_case.get("name", "")))
    case = {
        "stable_case_id": _source_stable_case_id(source_case),
        "output_section": _output_section_from_module_path(str(source_case.get("module_path", ""))),
        "module": _module_from_source_case(source_case),
        "category": "human_added",
        "scenario": scenario,
        "preconditions": _labeled_value(str(source_case.get("preconditions", "")), PRECONDITIONS_LABEL),
        "steps": _source_steps(source_case.get("steps", [])),
        "remarks": _labeled_value(str(source_case.get("remarks", "")), REMARKS_LABEL),
        "tags": _source_tags(source_case.get("labels", [])),
        "markers": _source_markers(source_case.get("markers", [])),
        "priority": str(source_case.get("priority") or "P2"),
        "source_reference": {
            "generated_by": HUMAN_OVERLAY_GENERATED_BY,
            "source_xmind": str(human_xmind_path),
            "merge_action": "added_from_human_copy",
        },
        "unresolved_questions": [],
    }
    if _looks_negative_source_case(case):
        case["expected_error"] = {
            "code": "HUMAN_COPY_ERROR",
            "source": "human_xmind_copy",
            "description": "Expected error is preserved from a human-edited XMind copy; verify the exact vendor error response during QA.",
        }
    case["stable_case_id"] = case["stable_case_id"] or stable_case_key(case)
    return case


def _source_stable_case_id(source_case: dict[str, Any]) -> str:
    hidden = str(source_case.get("stable_case_id", "")).strip()
    if hidden:
        return hidden
    visible = str(source_case.get("case_id", "")).strip()
    return visible


def _source_steps(value: Any) -> list[dict[str, str]]:
    output = []
    if not isinstance(value, list):
        return output
    for step in value:
        if not isinstance(step, dict):
            continue
        output.append(
            {
                "step": str(step.get("step", "")),
                "expected": str(step.get("expected", "")),
            }
        )
    return output


def _source_markers(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output = []
    for marker in value:
        marker_id = str(marker).strip()
        if marker_id and marker_id not in output:
            output.append(marker_id)
    return output


def _human_case_index(
    cases: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    index: dict[str, dict[str, Any]] = {}
    duplicate_same_title: list[dict[str, str]] = []
    regenerated_human_ids: list[dict[str, str]] = []
    for case in cases:
        key = f"stable::{stable_case_key(case)}"
        if key in index:
            existing = index[key]
            if _normalize_title(str(existing.get("scenario", ""))) == _normalize_title(str(case.get("scenario", ""))):
                case["_skip_human_duplicate"] = True
                duplicate_same_title.append(
                    {
                        "stable_case_id": stable_case_key(case),
                        "scenario": str(case.get("scenario", "")),
                    }
                )
                continue

            original_id = stable_case_key(case)
            regenerated_id = _regenerated_human_case_key(case, original_id)
            case["stable_case_id"] = regenerated_id
            source_reference = case.setdefault("source_reference", {})
            if isinstance(source_reference, dict):
                source_reference["duplicated_from_stable_case_id"] = original_id
                source_reference["merge_action"] = "regenerated_duplicate_id_as_new_case"
            regenerated_human_ids.append(
                {
                    "original_stable_case_id": original_id,
                    "new_stable_case_id": regenerated_id,
                    "scenario": str(case.get("scenario", "")),
                }
            )
            key = f"stable::{regenerated_id}"

        index[key] = case
    return index, duplicate_same_title, regenerated_human_ids


def _matching_human_case(base_case: dict[str, Any], human_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return human_index.get(f"stable::{stable_case_key(base_case)}")


def _overlay_human_case(
    base_case: dict[str, Any], human_case: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    merged = deepcopy(base_case)
    fields = []
    warnings = []

    human_scenario = str(human_case.get("scenario", "")).strip()
    if human_scenario and human_scenario != str(base_case.get("scenario", "")).strip():
        merged["scenario"] = human_scenario
        fields.append("scenario")

    if base_case.get("output_section") != API_PARAMETER_TEST_SECTION:
        base_steps = base_case.get("steps", []) if isinstance(base_case.get("steps"), list) else []
        human_steps = human_case.get("steps", []) if isinstance(human_case.get("steps"), list) else []
        if not human_steps and base_steps:
            warnings.append(
                {
                    "code": "human_steps_empty",
                    "message": f"Human steps are empty for {stable_case_key(base_case)}; base steps kept.",
                }
            )
        elif _steps_changed(base_steps, human_steps):
            merged["steps"] = human_steps
            fields.append("steps")

    human_markers = _source_markers(human_case.get("markers", []))
    base_markers = _source_markers(base_case.get("markers", []))
    if human_markers != base_markers:
        merged["markers"] = human_markers
        fields.append("markers")

    if fields:
        existing_overrides = merged.get("human_overrides")
        if isinstance(existing_overrides, list):
            merged["human_overrides"] = sorted(set(existing_overrides).union(fields))
        else:
            merged["human_overrides"] = sorted(set(fields))

    return merged, fields, warnings


def _steps_changed(base_steps: list[Any], human_steps: list[Any]) -> bool:
    if len(base_steps) != len(human_steps):
        return True
    for base_step, human_step in zip(base_steps, human_steps):
        if _comparable_step(base_step) != _comparable_step(human_step):
            return True
    return False


def _comparable_step(step: Any) -> dict[str, str]:
    if not isinstance(step, dict):
        return {"step": "", "expected": ""}
    return {
        "step": _normalize_text(str(step.get("step", ""))),
        "expected": _normalize_text(str(step.get("expected", ""))),
    }


def _load_manifest(manifest_path: Path | None) -> dict[str, Any] | None:
    if not manifest_path or not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_merge_report(report_path: Path, vendor: str, report: dict[str, Any]) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_merge_report(vendor, report), encoding="utf-8")
    return report_path


def _render_merge_report(vendor: str, report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        f"# {vendor or 'Vendor'} Human XMind Merge Report",
        "",
        f"Status: {report.get('status', 'success')}",
        "",
        "## Summary",
        "",
        "| Item | Count |",
        "|---|---:|",
        f"| Base cases | {summary.get('base_cases', 0)} |",
        f"| Human copy cases | {summary.get('human_cases', 0)} |",
        f"| Overridden by human | {summary.get('overridden', 0)} |",
        f"| Added from human | {summary.get('added_from_human', 0)} |",
        f"| Deleted by human | {summary.get('deleted_by_human', 0)} |",
        f"| New from base | {summary.get('new_from_base', 0)} |",
        f"| Base-only kept because manifest missing | {summary.get('base_only_without_manifest', 0)} |",
        f"| Regenerated human IDs | {summary.get('regenerated_human_ids', 0)} |",
        f"| Duplicate same title skipped | {summary.get('duplicate_same_title', 0)} |",
        f"| Warnings | {summary.get('warnings', 0)} |",
        f"| Conflicts | {summary.get('conflicts', 0)} |",
        "",
    ]
    lines.extend(_table_section("Overridden By Human", report.get("overridden", []), ("stable_case_id", "fields")))
    lines.extend(_table_section("Added From Human", report.get("added_from_human", []), ("stable_case_id", "scenario")))
    lines.extend(_table_section("Deleted By Human", report.get("deleted_by_human", []), ("stable_case_id",)))
    lines.extend(
        _table_section(
            "Regenerated Human IDs",
            report.get("regenerated_human_ids", []),
            ("original_stable_case_id", "new_stable_case_id", "scenario"),
        )
    )
    lines.extend(_table_section("Duplicate Same Title Skipped", report.get("duplicate_same_title", []), ("stable_case_id", "scenario")))
    lines.extend(_table_section("Warnings", report.get("warnings", []), ("code", "message")))
    lines.extend(_table_section("Conflicts", report.get("conflicts", []), ("code", "stable_case_id")))
    return "\n".join(lines).rstrip() + "\n"


def _table_section(title: str, rows: Any, fields: tuple[str, ...]) -> list[str]:
    lines = [f"## {title}", ""]
    if not isinstance(rows, list) or not rows:
        return lines + ["None", ""]
    lines.append("| " + " | ".join(fields) + " |")
    lines.append("|" + "|".join("---" for _ in fields) + "|")
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = []
        for field in fields:
            value = row.get(field, "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            values.append(_escape_markdown_cell(str(value)))
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return lines


def _scenario_from_source_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        return f"{CASE_TITLE_PREFIX}human added case"
    return stripped if stripped.startswith(CASE_TITLE_PREFIX) else f"{CASE_TITLE_PREFIX}{stripped}"


def _output_section_from_module_path(module_path: str) -> str:
    parts = [part.strip() for part in module_path.split(">") if part.strip()]
    if API_PARAMETER_TEST_SECTION in parts:
        return API_PARAMETER_TEST_SECTION
    if "User Behavior" in parts:
        index = parts.index("User Behavior")
        return " > ".join(parts[index : min(len(parts), index + 3)])
    return " > ".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "Human Added")


def _module_from_source_case(source_case: dict[str, Any]) -> str:
    module_title = str(source_case.get("module_title", "")).strip()
    if module_title:
        return module_title
    parts = [part.strip() for part in str(source_case.get("module_path", "")).split(">") if part.strip()]
    return parts[-1] if parts else "Human Added"


def _labeled_value(value: str, label: str) -> str:
    stripped = value.strip()
    if not stripped:
        return label
    return stripped if stripped.startswith(label) else f"{label}\n{stripped}"


def _source_tags(labels: Any) -> list[str]:
    output = []
    values = labels if isinstance(labels, list) else [labels]
    for value in values:
        for item in str(value).split(","):
            clean = item.strip()
            if clean:
                output.append(clean)
    return _unique(output)


def _looks_negative_source_case(case: dict[str, Any]) -> bool:
    text_parts = [
        str(case.get("scenario", "")),
        str(case.get("preconditions", "")),
        str(case.get("remarks", "")),
    ]
    for step in case.get("steps", []) or []:
        if isinstance(step, dict):
            text_parts.append(str(step.get("step", "")))
            text_parts.append(str(step.get("expected", "")))
    text = " ".join(text_parts).lower()
    negative_keywords = (
        "fail",
        "failed",
        "failure",
        "reject",
        "rejected",
        "error",
        "invalid",
        "missing",
        "duplicate",
        "timeout",
        "not found",
        "exceed",
        "negative",
    )
    return any(keyword in text for keyword in negative_keywords)


def _human_case_key(case: dict[str, Any]) -> str:
    module = _module_key(case)
    scenario = str(case.get("scenario", ""))
    return f"human::{module}::{_short_hash(module + '|' + scenario)}"


def _regenerated_human_case_key(case: dict[str, Any], original_id: str) -> str:
    module = _module_key(case)
    steps = json.dumps(case.get("steps", []), ensure_ascii=False, sort_keys=True)
    seed = "|".join([original_id, module, str(case.get("scenario", "")), steps])
    return f"human::{module}::{_short_hash(seed)}"


def _module_key(case: dict[str, Any]) -> str:
    return _slug(str(case.get("output_section") or case.get("module") or "human_added"))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "unknown"


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _normalize_title(value: str) -> str:
    text = str(value).strip()
    text = re.sub(r"^\s*(case|用例)\s*[：:]\s*", "", text, flags=re.IGNORECASE)
    return _normalize_text(text)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("：", ":")).strip().lower()


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
