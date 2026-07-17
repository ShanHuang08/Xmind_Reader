"""Normalize User Behavior wording when vendor endpoints use Debit/Credit terms."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


BET_SETTLE_SECTION = "User Behavior > Bet and Settle"
CANCEL_BET_SECTION = "User Behavior > Cancel Bet"
DEBIT_CREDIT_SECTION = "User Behavior > Debit and Credit"
CANCEL_DEBIT_SECTION = "User Behavior > Cancel Debit"

USER_BEHAVIOR_GENERATED_BY = "user-behavior-reference-generator/v1"
VENDOR_TEST_SCENARIO_GENERATED_BY = "vendor-test-scenario-import/v1"

_TERM_PATTERN = re.compile(r"\b(settlement|settle|bet)\b", re.IGNORECASE)
_DEBIT_PATTERN = re.compile(r"\bdebit\b", re.IGNORECASE)
_CREDIT_PATTERN = re.compile(r"\bcredit\b", re.IGNORECASE)


def normalize_user_behavior_debit_credit_terms(
    context: dict[str, Any], cases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return cases with bet/settle wording changed for Debit/Credit endpoint docs.

    The transformation is intentionally limited to generated User Behavior cases.
    It runs before cases are written into the draft, so downstream draft and XMind
    output already contain the vendor-facing wording.
    """
    if not _uses_debit_credit_endpoints(context):
        return cases

    normalized: list[dict[str, Any]] = []
    for case in cases:
        if not _is_generated_user_behavior_case(case):
            normalized.append(case)
            continue
        normalized.append(_normalize_case(case))
    return normalized


def debit_credit_output_section_aliases() -> dict[str, set[str]]:
    """Return validator aliases for Debit/Credit-normalized User Behavior sections."""
    return {
        BET_SETTLE_SECTION: {DEBIT_CREDIT_SECTION},
        CANCEL_BET_SECTION: {CANCEL_DEBIT_SECTION},
    }


def _uses_debit_credit_endpoints(context: dict[str, Any]) -> bool:
    roles = [item for item in context.get("endpoint_roles", []) if isinstance(item, dict)]
    bet_text = " ".join(_endpoint_text(item) for item in roles if item.get("role") == "bet")
    settlement_text = " ".join(
        _endpoint_text(item) for item in roles if item.get("role") == "settlement"
    )
    combined_text = " ".join(
        _endpoint_text(item) for item in roles if item.get("role") == "combined_bet_settlement"
    )
    has_debit = bool(_DEBIT_PATTERN.search(bet_text) or _DEBIT_PATTERN.search(combined_text))
    has_credit = bool(
        _CREDIT_PATTERN.search(settlement_text) or _CREDIT_PATTERN.search(combined_text)
    )
    return has_debit and has_credit


def _endpoint_text(endpoint: dict[str, Any]) -> str:
    values: list[str] = []
    for key in (
        "endpoint",
        "endpoint_name",
        "api_name",
        "section",
        "generation_note",
        "keywords",
    ):
        value = endpoint.get(key)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        else:
            values.append(str(value or ""))
    return " ".join(values)


def _is_generated_user_behavior_case(case: dict[str, Any]) -> bool:
    if not str(case.get("output_section", "")).startswith("User Behavior >"):
        return False
    source = case.get("source_reference", {})
    return isinstance(source, dict) and source.get("generated_by") in {
        USER_BEHAVIOR_GENERATED_BY,
        VENDOR_TEST_SCENARIO_GENERATED_BY,
    }


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    output = deepcopy(case)
    output["output_section"] = _normalize_output_section(str(output.get("output_section", "")))

    for key in ("scenario", "module", "preconditions", "remarks"):
        if isinstance(output.get(key), str):
            output[key] = _normalize_text(output[key])

    if isinstance(output.get("steps"), list):
        output["steps"] = [_normalize_step(step) for step in output["steps"]]

    if isinstance(output.get("tags"), list):
        output["tags"] = [_normalize_text(str(tag)) for tag in output["tags"]]

    return output


def _normalize_step(step: Any) -> Any:
    if not isinstance(step, dict):
        return step
    normalized = deepcopy(step)
    for key in ("step", "expected"):
        if isinstance(normalized.get(key), str):
            normalized[key] = _normalize_text(normalized[key])
    return normalized


def _normalize_output_section(value: str) -> str:
    if value == BET_SETTLE_SECTION:
        return DEBIT_CREDIT_SECTION
    if value == CANCEL_BET_SECTION:
        return CANCEL_DEBIT_SECTION
    return _normalize_text(value)


def _normalize_text(value: str) -> str:
    return _TERM_PATTERN.sub(_replacement, value)


def _replacement(match: re.Match[str]) -> str:
    term = match.group(1).lower()
    if term == "bet":
        return "Debit"
    return "Credit"
