"""Extract compact test case knowledge from parsed XMind data."""

from __future__ import annotations

import re
import json
import hashlib
from collections import Counter
from typing import Any


TAG_RULES: dict[str, tuple[str, ...]] = {
    "positive": ("success", "successful", "normal", "ok", "succeed", "正确", "成功"),
    "negative": ("invalid", "error", "failed", "wrong", "not found", "失败", "异常"),
    "boundary": (
        "boundary",
        "limit",
        "exceed",
        "blank",
        "null",
        "empty",
        "maximum",
        "minimum",
    ),
    "validation": ("validation", "invalid", "parameter", "must not", "校验", "验证"),
    "idempotency": ("idempotency", "duplicate", "same transaction", "重复"),
    "retry": ("retry", "again", "re-send", "重试"),
    "timeout": ("timeout", "time out", "超时"),
    "rollback": ("rollback", "roll back", "回滚"),
    "cancel": ("cancel", "取消"),
    "free_spin": ("free spin", "freespin", "free game", "免费旋转"),
    "wallet": ("wallet", "balance", "credit", "debit", "余额"),
    "bet": ("bet", "wager", "下注"),
    "settlement": ("settlement", "settle", "payout", "winloss", "结算"),
    "jackpot": ("jackpot", "奖池"),
    "db_check": ("db", "database", "sql", "opensearch", "record created", "record"),
    "api_check": ("api", "response", "request", "endpoint"),
    "encryption": ("encrypt", "decrypt", "signature", "hash", "sign", "加密"),
}

DB_KEYWORDS = ("db", "database", "sql", "opensearch", "gabo", "vendor bo", "record")
VALIDATION_KEYWORDS = (
    "check",
    "verify",
    "response",
    "error code",
    "balance",
    "record",
    "must",
    "equals",
    "equal",
    "show",
)


def extract_knowledge(parsed_files: list[dict[str, Any]]) -> dict[str, Any]:
    """Build compact knowledge cases and extraction statistics."""
    cases: list[dict[str, Any]] = []
    for parsed in parsed_files:
        for source_case in parsed.get("source_cases", []):
            source_case = dict(source_case)
            source_case["source_file"] = parsed.get("source_file", "")
            cases.append(_to_knowledge_case(source_case, len(cases) + 1))

    summary = _build_extraction_report(cases, parsed_files)
    return {"cases": cases, "report": summary}


def _to_knowledge_case(source_case: dict[str, Any], index: int) -> dict[str, Any]:
    generated_id = f"TC_{index:04d}"
    case_id = str(source_case.get("case_id") or generated_id)
    steps = source_case.get("steps", [])
    step_texts = [_compact_text(step.get("step", "")) for step in steps if step.get("step")]
    expected_texts = [
        _compact_text(step.get("expected", "")) for step in steps if step.get("expected")
    ]
    full_text = " ".join(
        [
            source_case.get("name", ""),
            source_case.get("module_path", ""),
            source_case.get("preconditions", ""),
            source_case.get("remarks", ""),
            " ".join(step_texts),
            " ".join(expected_texts),
        ]
    )
    tags = sorted(_detect_tags(full_text))
    module = _module_name(source_case)
    api_name = _api_name(source_case, module)

    case = _drop_empty(
        {
            "id": case_id,
            "generated_id": generated_id if case_id != generated_id else "",
            "api_name": api_name,
            "module": module,
            "scenario": _compact_text(source_case.get("name", "")),
            "title": _compact_text(source_case.get("name", "")),
            "path": source_case.get("module_path", ""),
            "level": len([part for part in source_case.get("raw_path", []) if part]),
            "parent_topic": _parent_topic(source_case),
            "child_topic": _compact_text(source_case.get("name", "")),
            "preconditions": _compact_text(source_case.get("preconditions", "")),
            "steps": step_texts,
            "expected_results": expected_texts,
            "validation_points": _validation_points(step_texts, expected_texts),
            "db_checks": _db_checks(step_texts, expected_texts),
            "tags": tags,
            "priority": source_case.get("priority", ""),
            "source": {
                "xmind_file": source_case.get("source_file", ""),
                "sheet": source_case.get("sheet", ""),
                "topic_id": source_case.get("raw_topic_id", ""),
            },
        }
    )
    case["content_hash"] = _case_content_hash(case)
    return case


def _module_name(case: dict[str, Any]) -> str:
    if case.get("module_title"):
        return _compact_text(case["module_title"])
    parts = [part.strip() for part in case.get("module_path", "").split(">") if part.strip()]
    return parts[-1] if parts else "unclassified"


def _api_name(case: dict[str, Any], module: str) -> str:
    text = "\n".join([case.get("preconditions", ""), case.get("module_path", "")])
    match = re.search(r"(/api/[^\s<]+)", text)
    if match:
        return match.group(1).strip()
    return module


def _parent_topic(case: dict[str, Any]) -> str:
    path = case.get("raw_path", [])
    return path[-2] if len(path) >= 2 else ""


def _detect_tags(text: str) -> set[str]:
    lowered = text.lower()
    tags = {
        tag
        for tag, keywords in TAG_RULES.items()
        if any(_contains_keyword(lowered, keyword.lower()) for keyword in keywords)
    }
    return tags or {"unclassified"}


def _contains_keyword(text: str, keyword: str) -> bool:
    if re.search(r"[\u4e00-\u9fff\s_-]", keyword):
        return keyword in text
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _validation_points(steps: list[str], expected: list[str]) -> list[str]:
    points = []
    for text in steps + expected:
        lowered = text.lower()
        if any(keyword in lowered for keyword in VALIDATION_KEYWORDS):
            points.append(text)
    return _unique(points)


def _db_checks(steps: list[str], expected: list[str]) -> list[str]:
    checks = []
    for text in steps + expected:
        lowered = text.lower()
        if any(keyword in lowered for keyword in DB_KEYWORDS):
            checks.append(text)
    return _unique(checks)


def _build_extraction_report(
    cases: list[dict[str, Any]], parsed_files: list[dict[str, Any]]
) -> dict[str, Any]:
    module_counts = Counter(case.get("module", "unclassified") for case in cases)
    tag_counts = Counter(tag for case in cases for tag in case.get("tags", []))
    return {
        "files_opened": [item.get("source_file", "") for item in parsed_files],
        "total_files": len(parsed_files),
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


def _compact_text(value: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (value or "").strip())


def _unique(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in ("", None, [], {})}


def _case_content_hash(case: dict[str, Any]) -> str:
    payload = {
        key: case.get(key)
        for key in (
            "api_name",
            "module",
            "scenario",
            "path",
            "preconditions",
            "steps",
            "expected_results",
            "validation_points",
            "db_checks",
            "tags",
            "priority",
            "source",
        )
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
