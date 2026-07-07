"""Write a compact Markdown summary for generated test cases."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


USER_BEHAVIOR_GENERATOR = "user-behavior-reference-generator/v1"
API_PARAMETER_SECTION = "API parameter test"


def write_test_case_summary(draft: dict[str, Any], output_path: Path | str) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_test_case_summary(draft), encoding="utf-8")
    return output


def render_test_case_summary(draft: dict[str, Any]) -> str:
    vendor = str(draft.get("vendor") or "Vendor")
    cases = [case for case in draft.get("test_cases", []) if isinstance(case, dict)]
    user_behavior_cases = [
        case
        for case in cases
        if case.get("source_reference", {}).get("generated_by") == USER_BEHAVIOR_GENERATOR
    ]
    api_parameter_cases = [
        case
        for case in cases
        if case.get("output_section") == API_PARAMETER_SECTION
        or case.get("category") == "parameter_validation"
    ]

    lines = [
        f"# {vendor} Test Case Summary",
        "",
        f"{vendor} 這次總共產生 {len(cases)} 筆，其中：",
        "",
        "| Type | Count |",
        "|---|---:|",
        f"| User Behavior | {len(user_behavior_cases)} |",
        f"| API parameter test | {len(api_parameter_cases)} |",
        "",
        "## User Behavior 抽到的種類",
        "",
        "| User_Behavior_map 分支 | Category | Output section | Count |",
        "|---|---|---|---:|",
    ]

    for row in _user_behavior_rows(user_behavior_cases):
        lines.append(
            "| {source_path} | {category} | {output_section} | {count} |".format(
                source_path=_escape_cell(row["source_path"]),
                category=_escape_cell(row["category"]),
                output_section=_escape_cell(row["output_section"]),
                count=row["count"],
            )
        )

    lines.extend(["", "## 簡單分析", ""])
    lines.extend(_analysis_lines(draft, user_behavior_cases, api_parameter_cases))
    return "\n".join(lines).rstrip() + "\n"


def _user_behavior_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, str, str]] = Counter()
    for case in cases:
        source_path = str(case.get("source_reference", {}).get("source_path", ""))
        category = str(case.get("category", ""))
        output_section = str(case.get("output_section", ""))
        counter[(source_path, category, output_section)] += 1
    return [
        {
            "source_path": source_path,
            "category": category,
            "output_section": output_section,
            "count": count,
        }
        for (source_path, category, output_section), count in counter.most_common()
    ]


def _analysis_lines(
    draft: dict[str, Any],
    user_behavior_cases: list[dict[str, Any]],
    api_parameter_cases: list[dict[str, Any]],
) -> list[str]:
    selected = draft.get("reference_selection", {}).get("selected_categories", [])
    endpoint_analysis = draft.get("endpoint_analysis", {})
    topology = endpoint_analysis.get("endpoint_topology", {})
    semantics = endpoint_analysis.get("parameter_semantics", {})

    lines = [
        f"- User Behavior 佔 {len(user_behavior_cases)} 筆，主要由 selected categories 決定。",
        f"- API parameter test 佔 {len(api_parameter_cases)} 筆，主要由 endpoint request parameters 產生。",
    ]
    if selected:
        lines.append(f"- Selected categories: {', '.join(str(item) for item in selected)}")
    bet_mode = topology.get("bet", {}).get("mode")
    settlement_mode = topology.get("settlement", {}).get("mode")
    if bet_mode or settlement_mode:
        lines.append(
            "- Endpoint topology: bet={bet}, settlement={settlement}.".format(
                bet=bet_mode or "unknown",
                settlement=settlement_mode or "unknown",
            )
        )
    if semantics.get("free_spin_control"):
        lines.append("- 偵測到 FreeSpin 相關參數，因此有抽 FreeSpin 測項。")
    if semantics.get("round_end_control"):
        lines.append("- 偵測到 round-end control 參數，因此抽 Has round-end control parameter 分支。")
    return lines


def _escape_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
