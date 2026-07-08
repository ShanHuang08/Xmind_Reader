"""Generate structured draft test cases from parsed vendor details."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import time
from pathlib import Path
from typing import Any

from generator.case_generation_context import build_generation_context, load_draft, save_draft
from generator.draft_schema import (
    API_PARAMETER_CASE_TITLE_TEMPLATE,
    API_PARAMETER_TEST_SECTION,
    KNOWLEDGE_CATEGORY_TO_XMIND_SECTION,
    PRECONDITIONS_LABEL,
    REMARKS_LABEL,
)
from generator.draft_validator import validate_draft
from generator.reference_selector import selected_categories, select_reference_files


GENERATED_BY = "deterministic-parameter-generator/v1"
USER_BEHAVIOR_GENERATED_BY = "user-behavior-reference-generator/v1"

CATEGORY_OUTPUT_PRIORITY = [
    "launch_game",
    "balance",
    "bet",
    "settlement",
    "amount_precision",
    "rollback",
    "authenticate",
    "authentication_is_necessary",
    "bet_and_settle",
    "bet_and_settle_has_round_end_control_parameter",
    "multiple_bets",
    "multiple_bets_one_bet_endpoint",
    "multiple_bets_two_bet_endpoint",
    "multiple_settlements",
    "multiple_settlements_has_round_end_control_parameter",
    "multiple_settlements_no_round_end_control_parameter",
    "rollback_bet",
    "rollback_settled_bet",
    "modify_settlement_adjustment",
    "idempotency",
    "freespin",
    "jackpot",
    "slot_game",
    "live_game",
    "arcade_game",
    "mini_game",
]


def generate_test_cases_for_draft(
    draft: dict[str, Any],
    xmind_detail_root: Path | str = "xmind_detail",
    include_parameter_validation: bool = True,
) -> list[dict[str, Any]]:
    """Generate cases from a draft object.

    The first implementation covers API parameter validation because those cases
    are fully derivable from endpoint request parameter tables.
    """
    context = build_generation_context(draft)
    categories = selected_categories(
        context.get("capability_profile", {}), context.get("endpoint_analysis", {})
    )
    categories = _merge_categories(categories, _game_type_categories(context))
    references = [str(path) for path in select_reference_files(xmind_detail_root, categories)]
    cases: list[dict[str, Any]] = []
    cases.extend(_user_behavior_cases(context, xmind_detail_root, categories))

    if include_parameter_validation:
        cases.extend(_parameter_validation_cases(context, references))

    return cases


def generate_test_cases_file(
    draft_path: Path | str,
    xmind_detail_root: Path | str = "xmind_detail",
    replace_generated: bool = True,
) -> Path:
    """Generate cases and write them back into draft_test_cases.json."""
    path = Path(draft_path)
    draft = load_draft(path)
    generated_cases = generate_test_cases_for_draft(draft, xmind_detail_root=xmind_detail_root)

    existing_cases = draft.get("test_cases", [])
    if not isinstance(existing_cases, list):
        existing_cases = []

    if replace_generated:
        existing_cases = [
            case
            for case in existing_cases
            if not (
                isinstance(case, dict)
                and case.get("source_reference", {}).get("generated_by")
                in {GENERATED_BY, USER_BEHAVIOR_GENERATED_BY}
            )
        ]

    draft["status"] = "generated_test_cases"
    draft["reference_selection"] = {
        "selected_categories": _merge_categories(
            selected_categories(
                draft.get("capability_profile", {}), draft.get("endpoint_analysis", {})
            ),
            _game_type_categories(build_generation_context(draft)),
        ),
        "xmind_detail_root": str(xmind_detail_root),
    }
    draft["test_cases"] = existing_cases + generated_cases
    result = validate_draft(draft)
    if not result.valid:
        messages = "; ".join(f"{issue.path}: {issue.message}" for issue in result.errors)
        raise ValueError(f"Generated draft failed validation: {messages}")

    return save_draft(draft, path)


def _merge_categories(primary: list[str], extra: list[str]) -> list[str]:
    merged = []
    for category in primary + extra:
        if category not in merged:
            merged.append(category)
    return _sort_categories_for_output(merged)


def _sort_categories_for_output(categories: list[str]) -> list[str]:
    priority = {category: index for index, category in enumerate(CATEGORY_OUTPUT_PRIORITY)}
    return sorted(categories, key=lambda category: (priority.get(category, len(priority)), category))


def _game_type_categories(context: dict[str, Any]) -> list[str]:
    categories = set()
    for item in context.get("game_codes", []):
        text = " ".join(
            str(item.get(key, "")) for key in ("game_type", "game_name", "game_code")
        ).lower()
        if "slot" in text:
            categories.add("slot_game")
        if "live" in text or "casino" in text:
            categories.add("live_game")
        if "arcade" in text or str(item.get("game_code", "")).upper().startswith("IDNA_"):
            categories.add("arcade_game")
        if "mini" in text or "crash" in text:
            categories.add("mini_game")
    if _vendor_checklist_enabled(context, "Game Type"):
        categories.add("mini_game")
    return sorted(categories)


def _vendor_checklist_enabled(context: dict[str, Any], checklist_name: str) -> bool:
    profile = context.get("capability_profile", {})
    target = checklist_name.strip().lower()
    for item in profile.get("vendor_master_checklist", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        if name == target and bool(item.get("enabled")):
            return True
    return False


def _user_behavior_cases(
    context: dict[str, Any], xmind_detail_root: Path | str, categories: list[str]
) -> list[dict[str, Any]]:
    root = Path(xmind_detail_root) / "User_Behavior_map" / "modules"
    if not root.exists():
        return []

    selected = set(categories)
    cases = []
    seen: set[str] = set()
    for category in categories:
        for module_name, path_fragment in _user_behavior_selectors(category, selected):
            module_path = root / f"{module_name}.json"
            if not module_path.exists():
                continue
            for reference_case in _load_reference_module_cases(module_path):
                path = str(reference_case.get("path", ""))
                if not _path_matches(path, path_fragment):
                    continue
                key = str(reference_case.get("content_hash") or reference_case.get("id") or "")
                key = f"{key or reference_case.get('scenario', '')}:{path}"
                if key in seen:
                    continue
                seen.add(key)
                cases.append(
                    _user_behavior_case(context, category, reference_case, str(module_path))
                )
    return cases


def _user_behavior_selectors(
    category: str, selected_categories: set[str]
) -> list[tuple[str, str]]:
    if category == "launch_game":
        return [("launch_game", "Mandatory > launch game")]
    if category == "balance":
        return [("get_player_balance", "Mandatory > get player balance")]
    if category in {"bet", "settlement", "amount_precision"}:
        return [("bet_and_settle", "Mandatory > bet and settle")]
    if category == "rollback":
        return [("cancel_bet", "Mandatory > cancel Bet")]
    if category == "authenticate":
        return [("authenticate", "Authenticate > Mandatory")]
    if category == "authentication_is_necessary":
        return [("bet_and_settle", "Authenticate > Authentication is necessary")]
    if category == "bet_and_settle":
        return [("bet_and_settle", "BetAndSettle > Mandatory")]
    if category == "bet_and_settle_has_round_end_control_parameter":
        return [("bet_and_settle", "BetAndSettle > Has round-end control parameter")]
    if category == "multiple_bets_one_bet_endpoint":
        return [("bet_and_settle", "Multiple Bets > one_bet_endpoint")]
    if category == "multiple_bets_two_bet_endpoint":
        return [("bet_and_settle", "Multiple Bets > two_bet_endpoint")]
    if category == "multiple_settlements_has_round_end_control_parameter":
        return [
            ("bet_and_settle", "Multiple Settlement > Has round-end control parameter"),
            ("debit_and_credit", "Multiple Settlement > Has round-end control parameter"),
        ]
    if category == "multiple_settlements_no_round_end_control_parameter":
        return [("bet_and_settle", "Multiple Settlement > No round-end control parameter")]
    if category in {"rollback_bet", "rollback_settled_bet"}:
        return [("cancel_bet", "rollback_by_bet")]
    if category == "modify_settlement_adjustment":
        return [("bet_and_settle", "modify_settlement_adjustment")]
    if category == "freespin":
        return [("bet_and_settle", "FreeSpin")]
    if category == "jackpot":
        return [("bet_and_settle", "jackpot")]
    if category == "idempotency":
        return [("bet_and_settle", "idempotency")]
    if category == "slot_game":
        return [("slot_game", "Game Type > Slot game")]
    if category == "live_game":
        return [("live_game", "Game Type > Live game")]
    if category == "arcade_game":
        return [("mini_game", "Game Type > Mini game")]
    if category == "mini_game":
        return [("mini_game", "Game Type > Mini game")]
    return []


def _load_reference_module_cases(module_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(module_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cases = payload.get("cases", [])
    return [case for case in cases if isinstance(case, dict)]


def _path_matches(path: str, fragment: str) -> bool:
    normalized_path = _normalize_reference_path(path)
    normalized_fragment = _normalize_reference_path(fragment)
    if "special test cases" in normalized_path:
        return False
    return normalized_fragment in normalized_path


def _normalize_reference_path(value: str) -> str:
    return " > ".join(part.strip().lower() for part in str(value).split(">") if part.strip())


def _user_behavior_case(
    context: dict[str, Any],
    category: str,
    reference_case: dict[str, Any],
    module_path: str,
) -> dict[str, Any]:
    output_section = KNOWLEDGE_CATEGORY_TO_XMIND_SECTION.get(
        category, "User Behavior > Bet and Settle"
    )
    scenario = _adapt_behavior_text(context, str(reference_case.get("scenario", "")))
    case = {
        "output_section": output_section,
        "module": _behavior_module(output_section, reference_case),
        "category": category,
        "scenario": scenario,
        "preconditions": _behavior_preconditions(context, category),
        "steps": _behavior_steps(context, reference_case),
        "remarks": _behavior_remarks(context, category),
        "tags": list(reference_case.get("tags", [])),
        "priority": reference_case.get("priority", "P2"),
        "source_reference": {
            "generated_by": USER_BEHAVIOR_GENERATED_BY,
            "source_case_id": reference_case.get("id", ""),
            "source_path": reference_case.get("path", ""),
            "xmind_reference_cases": [module_path],
        },
        "unresolved_questions": [],
    }
    case["expected_error"] = _behavior_expected_error(context)
    return case


def _behavior_module(output_section: str, reference_case: dict[str, Any]) -> str:
    if output_section.startswith("User Behavior > Game type"):
        return output_section.split(">")[-1].strip()
    return str(reference_case.get("module") or output_section.split(">")[-1].strip())


def _behavior_preconditions(context: dict[str, Any], category: str) -> str:
    endpoint = _endpoint_for_behavior_category(context, category)
    if endpoint:
        return _preconditions(context, endpoint)
    return _launch_preconditions(context)


def _behavior_steps(context: dict[str, Any], reference_case: dict[str, Any]) -> list[dict[str, str]]:
    steps = reference_case.get("steps", [])
    expected = reference_case.get("expected_results", [])
    if not isinstance(steps, list):
        steps = []
    if not isinstance(expected, list):
        expected = []
    output = []
    for index, step in enumerate(steps):
        expected_text = expected[index] if index < len(expected) else "The behavior matches the expected wallet flow."
        output.append(
            {
                "step": _adapt_behavior_text(context, str(step)),
                "expected": _adapt_behavior_text(context, str(expected_text)),
            }
        )
    if not output:
        output.append(
            {
                "step": "Execute the vendor behavior flow.",
                "expected": "The API returns the expected result.",
            }
        )
    return output


def _behavior_remarks(context: dict[str, Any], category: str) -> str:
    if category == "launch_game":
        return _launch_remarks(context)
    endpoint = _endpoint_for_behavior_category(context, category)
    if endpoint:
        return _remarks(endpoint, {"name": ""})
    return _generic_behavior_remarks(category)


def _behavior_expected_error(context: dict[str, Any]) -> dict[str, Any]:
    parameter_error = context.get("parameter_error", {})
    code = str(parameter_error.get("code") or "UNKNOWN_ERROR")
    description = str(parameter_error.get("description") or parameter_error.get("context") or "Error")
    source = str(parameter_error.get("source") or "inferred_from_vendor_codes")
    output = {
        "code": code,
        "source": source,
        "description": description,
    }
    if source.startswith("inferred"):
        output["inference_reason"] = (
            "No documented behavior-specific error code was found; review against the actual vendor response."
        )
    return output


def _adapt_behavior_text(context: dict[str, Any], value: str) -> str:
    endpoints = _role_endpoint_map(context)
    replacements = {
        "/api/v1/esoterica/authenticate": endpoints.get("authentication", ""),
        "/api/v1/esoterica/auth": endpoints.get("authentication", ""),
        "/api/v1/esoterica/bet": endpoints.get("bet", ""),
        "/api/v1/esoterica/result": endpoints.get("settlement", ""),
        "/api/v1/esoterica/balance": endpoints.get("balance_check", ""),
        "/api/v1/esoterica/rollback": endpoints.get("cancel_bet", "") or endpoints.get("rollback", ""),
        "EGTD_": context.get("case_authoring_rules", {}).get("default_game_code", ""),
    }
    adapted = value
    for old, new in replacements.items():
        if new:
            adapted = adapted.replace(old, new)
    return adapted


def _role_endpoint_map(context: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for endpoint in context.get("endpoint_roles", []):
        role = str(endpoint.get("role", ""))
        path = str(endpoint.get("endpoint", ""))
        if role and path and role not in output:
            output[role] = path
    return output


def _endpoint_for_behavior_category(context: dict[str, Any], category: str) -> dict[str, Any]:
    preferred_roles = {
        "authenticate": ["authentication"],
        "balance": ["balance_check", "authentication"],
        "bet": ["bet"],
        "amount_precision": ["bet"],
        "multiple_bets": ["bet"],
        "multiple_bets_one_bet_endpoint": ["bet"],
        "multiple_bets_two_bet_endpoint": ["bet"],
        "settlement": ["settlement"],
        "multiple_settlements": ["settlement"],
        "multiple_settlements_has_round_end_control_parameter": ["settlement"],
        "multiple_settlements_no_round_end_control_parameter": ["settlement"],
        "bet_and_settle": ["combined_bet_settlement", "bet", "settlement"],
        "bet_and_settle_has_round_end_control_parameter": ["combined_bet_settlement", "bet", "settlement"],
        "authentication_is_necessary": ["bet", "settlement", "authentication"],
        "rollback": ["cancel_bet", "rollback"],
        "rollback_bet": ["cancel_bet", "rollback"],
        "rollback_settled_bet": ["cancel_bet", "rollback"],
        "modify_settlement_adjustment": ["settlement"],
        "freespin": ["settlement"],
        "jackpot": ["settlement"],
        "idempotency": ["settlement", "bet"],
        "slot_game": ["bet", "settlement"],
        "live_game": ["bet", "settlement"],
        "arcade_game": ["bet", "settlement"],
        "mini_game": ["bet", "settlement"],
    }.get(category, [])
    endpoints = [item for item in context.get("endpoint_roles", []) if isinstance(item, dict)]
    for role in preferred_roles:
        for endpoint in endpoints:
            if endpoint.get("role") == role:
                return endpoint
    return {}


def _launch_preconditions(context: dict[str, Any]) -> str:
    game_code = context.get("case_authoring_rules", {}).get("default_game_code") or "<confirm gameCode>"
    return (
        f"{PRECONDITIONS_LABEL}\n"
        f"1. launch game {game_code}\n"
        "2. url：/game/url\n"
        f"3. test account：{context.get('default_test_account', '')}"
    )


def _launch_remarks(context: dict[str, Any]) -> str:
    payload = {
        "traceId": "{{traceId}}",
        "username": context.get("default_test_account", ""),
        "gameCode": context.get("case_authoring_rules", {}).get("default_game_code", ""),
        "language": "en",
        "platform": "WEB",
        "currency": _default_currency(context),
        "lobbyUrl": "https://www.google.com/",
        "ipAddress": "192.228.180.86",
    }
    return (
        f"{REMARKS_LABEL}\n"
        "API request parameters：\n"
        "<code>\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "</code>"
    )


def _generic_behavior_remarks(category: str) -> str:
    return (
        f"{REMARKS_LABEL}\n"
        f"API request parameters for `{category}` need to be filled from the target vendor endpoint. "
        "Do not reuse the launch-game `/game/url` payload for this case."
    )


def _default_currency(context: dict[str, Any]) -> str:
    for endpoint in context.get("endpoint_roles", []):
        value = _find_example_value(endpoint.get("request_example", {}), "currency")
        if value:
            return str(value)
    return "PHP"


def _parameter_validation_cases(
    context: dict[str, Any], reference_files: list[str]
) -> list[dict[str, Any]]:
    cases = []
    for endpoint in context.get("endpoint_roles", []):
        endpoint_name = endpoint.get("endpoint", "")
        if not endpoint_name:
            continue
        for parameter in _path_parameters(endpoint):
            cases.append(_parameter_case(context, endpoint, parameter, reference_files))
        for parameter in _expanded_request_parameters(endpoint):
            parameter_name = parameter.get("name", "")
            if not parameter_name:
                continue
            cases.append(_parameter_case(context, endpoint, parameter, reference_files))
    return cases


def _path_parameters(endpoint: dict[str, Any]) -> list[dict[str, Any]]:
    endpoint_name = str(endpoint.get("endpoint", ""))
    names = []
    for match in re.finditer(r"\{([^{}]+)\}", endpoint_name):
        name = match.group(1).strip()
        if name and name not in names:
            names.append(name)
    return [
        {
            "name": name,
            "type": "string",
            "required": "Y",
            "description": f"Path parameter in endpoint URL: {name}.",
            "source": "path_parameter",
        }
        for name in names
    ]


def _expanded_request_parameters(endpoint: dict[str, Any]) -> list[dict[str, Any]]:
    parameters = [
        parameter
        for parameter in endpoint.get("request_parameters", [])
        if isinstance(parameter, dict) and str(parameter.get("name", "")).strip()
    ]
    enriched_parameters = [
        _parameter_with_example_type(endpoint, parameter) for parameter in parameters
    ]
    child_parameters_by_parent = {
        str(parameter.get("name", "")).strip(): _child_parameters_from_request_example(
            endpoint, parameter
        )
        for parameter in enriched_parameters
    }
    nested_leaf_names = {
        str(child.get("name", "")).split("/")[-1]
        for children in child_parameters_by_parent.values()
        for child in children
        if "/" in str(child.get("name", ""))
    }
    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()

    for parameter in enriched_parameters:
        name = str(parameter.get("name", "")).strip()
        if _is_nested_only_parameter(endpoint, name, nested_leaf_names):
            continue
        if name not in seen:
            expanded.append(parameter)
            seen.add(name)
        for child in child_parameters_by_parent.get(name, []):
            child_name = str(child.get("name", "")).strip()
            if child_name and child_name not in seen:
                expanded.append(child)
                seen.add(child_name)

    return expanded


def _is_nested_only_parameter(
    endpoint: dict[str, Any], name: str, nested_leaf_names: set[str]
) -> bool:
    if name not in nested_leaf_names:
        return False
    return not _example_has_root_parameter(endpoint.get("request_example"), name)


def _example_has_root_parameter(data: Any, name: str) -> bool:
    return isinstance(data, dict) and name in data


def _parameter_with_example_type(
    endpoint: dict[str, Any], parameter: dict[str, Any]
) -> dict[str, Any]:
    name = str(parameter.get("name", "")).strip()
    if not name:
        return parameter
    if str(parameter.get("type", "")).strip():
        return parameter
    value = _find_example_value(endpoint.get("request_example"), name)
    if not isinstance(value, (dict, list)):
        return parameter
    enriched = dict(parameter)
    enriched["type"] = _type_name(value)
    return enriched


def _child_parameters_from_request_example(
    endpoint: dict[str, Any], parameter: dict[str, Any]
) -> list[dict[str, Any]]:
    parent_name = str(parameter.get("name", "")).strip()
    if not parent_name:
        return []
    value = _find_example_value(endpoint.get("request_example"), parent_name)
    if not isinstance(value, (dict, list)):
        return []
    return [
        _child_parameter(parent_name, child_path, child_value, parameter)
        for child_path, child_value in _walk_child_values(value)
    ]


def _walk_child_values(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return _walk_child_values(item, prefix)
        return []
    if not isinstance(value, dict):
        return []

    children: list[tuple[str, Any]] = []
    for key, child_value in value.items():
        child_path = f"{prefix}/{key}" if prefix else str(key)
        if isinstance(child_value, dict):
            children.extend(_walk_child_values(child_value, child_path))
        elif isinstance(child_value, list):
            nested = _walk_child_values(child_value, child_path)
            children.extend(nested or [(child_path, child_value)])
        else:
            children.append((child_path, child_value))
    return children


def _child_parameter(
    parent_name: str,
    child_path: str,
    child_value: Any,
    parent_parameter: dict[str, Any],
) -> dict[str, Any]:
    child = {
        "name": f"{parent_name}/{child_path}",
        "type": _type_name(child_value),
        "required": parent_parameter.get("required", ""),
        "description": (
            f"Child parameter inferred from request example under {parent_name}."
        ),
        "parent_parameter": parent_name,
        "source": "request_example_child",
    }
    return child


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _parameter_case(
    context: dict[str, Any],
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    reference_files: list[str],
) -> dict[str, Any]:
    endpoint_name = endpoint.get("endpoint", "")
    endpoint_display_name = _endpoint_display_name(endpoint_name)
    parameter_name = parameter.get("name", "")
    scenario = API_PARAMETER_CASE_TITLE_TEMPLATE.format(parameter=parameter_name)
    expected_error = _expected_error_for_parameter(context, parameter)
    if expected_error.get("source", "").startswith("inferred") and "inference_reason" not in expected_error:
        expected_error["inference_reason"] = (
            "No endpoint-specific parameter validation code was found; selected the closest documented vendor code."
        )

    return {
        "output_section": API_PARAMETER_TEST_SECTION,
        "module": endpoint_display_name,
        "category": "parameter_validation",
        "scenario": scenario,
        "endpoint": endpoint_name,
        "endpoint_name": endpoint_display_name,
        "endpoint_group": endpoint.get("role", ""),
        "endpoints": [endpoint_name],
        "parameter": parameter_name,
        "preconditions": _preconditions(context, endpoint),
        "steps": _parameter_steps(endpoint, parameter, expected_error),
        "remarks": _remarks(endpoint, parameter),
        "expected_error": expected_error,
        "tags": ["parameter_validation", "negative"],
        "priority": "P2",
        "source_reference": {
            "generated_by": GENERATED_BY,
            "vendor_doc": [endpoint_name],
            "xmind_reference_cases": reference_files,
        },
        "unresolved_questions": [],
    }


def _expected_error_for_parameter(
    context: dict[str, Any], parameter: dict[str, Any]
) -> dict[str, Any]:
    if parameter.get("source") == "path_parameter":
        return _path_parameter_error(context, str(parameter.get("name", "")))
    return deepcopy(context.get("parameter_error", {}))


def _path_parameter_error(context: dict[str, Any], parameter_name: str) -> dict[str, Any]:
    for item in context.get("error_codes", []):
        code = str(item.get("code", "")).strip()
        description = str(
            item.get("context") or item.get("message") or item.get("description") or ""
        ).strip()
        if code == "0" and "unauthorized" in description.lower():
            return {
                "code": code,
                "source": "documented",
                "description": description,
                "applies_to": parameter_name,
            }
    fallback = deepcopy(context.get("parameter_error", {}))
    fallback.setdefault("applies_to", parameter_name)
    return fallback


def _preconditions(
    context: dict[str, Any], endpoint: dict[str, Any]
) -> str:
    endpoint_name = endpoint.get("endpoint", "")
    game_code = context.get("case_authoring_rules", {}).get("default_game_code") or "<confirm gameCode>"
    return (
        f"{PRECONDITIONS_LABEL}\n"
        f"1. launch game {game_code}\n"
        f"2. url：{endpoint_name}\n"
        f"3. 测试账号：{context.get('default_test_account', '')}"
    )


def _remarks(endpoint: dict[str, Any], parameter: dict[str, Any]) -> str:
    focus_parameter = "" if parameter.get("source") == "path_parameter" else parameter.get("name", "")
    request = _request_payload(endpoint, focus_parameter)
    response = _response_payload(endpoint)
    return (
        f"{REMARKS_LABEL}\n"
        "API request parameters：\n"
        "<code>\n"
        f"{request}\n"
        "</code>\n"
        "Success response：\n"
        "<code>\n"
        f"{response}\n"
        "</code>"
    )


def _parameter_steps(
    endpoint: dict[str, Any], parameter: dict[str, Any], expected_error: dict[str, Any]
) -> list[dict[str, str]]:
    parameter_name = str(parameter.get("name", "parameter"))
    lowered = parameter_name.lower()
    code = expected_error.get("code", "UNKNOWN_PARAMETER_ERROR")
    error_response = _json_block(_expected_error_response(endpoint, expected_error))
    steps: list[dict[str, str]] = []

    if parameter.get("source") == "path_parameter":
        return _path_parameter_steps(endpoint, parameter, code, error_response)

    if _is_optional_parameter(parameter):
        return _optional_parameter_steps(endpoint, parameter)

    if _is_array_parameter(parameter):
        return _array_parameter_steps(endpoint, parameter, code, error_response)

    if "amount" in lowered:
        amount_cases = [
            (f"{parameter_name} doesn't set", f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}'),
            (f"{parameter_name} Input blank", f'"{parameter_name}": ""'),
            (
                f"{parameter_name} Input exceed 20 digit numbers",
                f'"{parameter_name}": 123456789012345678901',
            ),
            (f"{parameter_name} Input 9 decimal numbers", f'"{parameter_name}": 100.123456789'),
            (f"{parameter_name} Input negative number", f'"{parameter_name}": -100.0'),
            (f"{parameter_name} Input space", _space_request_line(endpoint, parameter)),
            (f"{parameter_name} Input string", f'"{parameter_name}": "test"'),
        ]
        return [
            _step_case(title, request_line, code, error_response)
            for title, request_line in amount_cases
        ]

    steps.append(
        _step_case(
            f"{parameter_name} doesn't set",
            f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}',
            code,
            error_response,
        )
    )
    steps.append(
        _step_case(
            f"{parameter_name} leave blank",
            f'"{parameter_name}": ""',
            code,
            error_response,
        )
    )
    steps.append(
        _step_case(
            f"{parameter_name} input space",
            _space_request_line(endpoint, parameter),
            code,
            error_response,
        )
    )

    if lowered == "currency":
        steps.append(
            _step_case("currency input wrong value", '"currency": "test"', code, error_response)
        )
    elif _is_timestamp_parameter(parameter):
        steps.append(
            _step_case(
                f"{parameter_name} input wrong data type",
                _wrong_data_type_request_line(parameter),
                code,
                error_response,
            )
        )
        steps.append(
            _step_case(
                f"{parameter_name} Input shorter timestamp",
                f'"{parameter_name}": 1722345',
                code,
                error_response,
            )
        )
    elif lowered == "hash":
        steps.append(
            _step_case("hash input wrong value", '"hash": "wrongvalue"', code, error_response)
        )
    else:
        steps.append(
            _step_case(
                f"{parameter_name} input wrong data type",
                _wrong_data_type_request_line(parameter),
                code,
                error_response,
            )
        )

    if lowered == "userid":
        steps.append(
            _step_case("userId input space", '"userId": " playerA "', code, error_response)
        )
    if _is_player_name_parameter(parameter_name):
        steps.append(
            _step_case(
                f"{parameter_name} input uppercase",
                f'"{parameter_name}": "PLAYERA"',
                code,
                error_response,
            )
        )
    return steps


def _path_parameter_steps(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    expected_code: str,
    error_response: str,
) -> list[dict[str, str]]:
    name = str(parameter.get("name", "pathParameter"))
    valid_value = _valid_path_parameter_value(endpoint, name)
    invalid_value = _invalid_path_parameter_value(name, valid_value)
    endpoint_name = str(endpoint.get("endpoint", ""))
    valid_url = endpoint_name.replace(f"{{{name}}}", valid_value)
    invalid_url = endpoint_name.replace(f"{{{name}}}", invalid_value)
    return [
        _step_case(
            f"{name} input wrong value",
            f"Correct url: {valid_url}\nTest url: {invalid_url}",
            expected_code,
            error_response,
        )
    ]


def _valid_path_parameter_value(endpoint: dict[str, Any], name: str) -> str:
    values = {
        "platformid": "zenith-qa",
    }
    return values.get(name.lower(), f"<valid {name}>")


def _invalid_path_parameter_value(name: str, valid_value: str) -> str:
    if name.lower() == "platformid":
        return "wrong-platform"
    return f"invalid-{valid_value}".strip("-")


def _optional_parameter_steps(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
) -> list[dict[str, str]]:
    parameter_name = str(parameter.get("name", "parameter"))
    lowered = parameter_name.lower()
    if _is_array_parameter(parameter):
        specs = _array_parameter_step_specs(endpoint, parameter)
    elif "amount" in lowered:
        specs = [
            (f"{parameter_name} doesn't set", _optional_amount_missing_request_line(parameter)),
            (f"{parameter_name} Input blank", f'"{parameter_name}": ""'),
            (
                f"{parameter_name} Input exceed 20 digit numbers",
                f'"{parameter_name}": 123456789012345678901',
            ),
            (f"{parameter_name} Input 9 decimal numbers", f'"{parameter_name}": 100.123456789'),
            (f"{parameter_name} Input negative number", f'"{parameter_name}": -100.0'),
            (f"{parameter_name} Input space", _space_request_line(endpoint, parameter)),
            (f"{parameter_name} Input string", f'"{parameter_name}": "test"'),
        ]
    else:
        specs = [
            (f"{parameter_name} doesn't set", f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}'),
            (f"{parameter_name} leave blank", f'"{parameter_name}": ""'),
            (f"{parameter_name} input space", _space_request_line(endpoint, parameter)),
            (
                f"{parameter_name} input wrong data type",
                _wrong_data_type_request_line(parameter),
            ),
        ]
    success_response = _json_block(_success_response(endpoint))
    return [_success_step_case(title, request_line, success_response) for title, request_line in specs]


def _optional_amount_missing_request_line(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "amount")).split("/")[-1] or "amount"
    return f'"{name}": 0'


def _array_parameter_steps(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    expected_code: str,
    error_response: str,
) -> list[dict[str, str]]:
    return [
        _step_case(title, request_line, expected_code, error_response)
        for title, request_line in _array_parameter_step_specs(endpoint, parameter)
    ]


def _array_parameter_step_specs(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
) -> list[tuple[str, str]]:
    name = str(parameter.get("name", "parameter"))
    placeholder = f"valid {name} parameters"
    missing_required_field = _first_required_array_item_field(endpoint, name)
    missing_placeholder = (
        f"{placeholder} without {missing_required_field}"
        if missing_required_field
        else f"{placeholder} with missing required field"
    )

    cases = [
        (f"{name} doesn't set", f'// "{name}": [ {placeholder} ]'),
        (f"{name} leave blank array", f'"{name}": []'),
        (f"{name} input null", f'"{name}": null'),
        (f"{name} input wrong data type", f'"{name}": "test"'),
        (
            f"{name} input object instead of array",
            f'"{name}": {{ {placeholder} }}',
        ),
        (f"{name} input empty object item", f'"{name}": [\n  {{}}\n]'),
        (
            f"{name} input item with missing required field",
            f'"{name}": [\n  {{ {missing_placeholder} }}\n]',
        ),
    ]
    return cases


def _first_required_array_item_field(
    endpoint: dict[str, Any],
    array_parameter_name: str,
) -> str:
    candidates = []
    for parameter in endpoint.get("request_parameters", []):
        name = str(parameter.get("name", "")).strip()
        if not name or name == array_parameter_name:
            continue
        required = str(parameter.get("required", "")).strip().upper()
        if not required.startswith("Y"):
            continue
        candidates.append(name)
    if not candidates:
        return ""
    seed = f"{endpoint.get('endpoint', '')}:{array_parameter_name}"
    index = sum(ord(char) for char in seed) % len(candidates)
    return candidates[index]


def _step_case(
    title: str, request_line: str, expected_code: str, error_response: str
) -> dict[str, str]:
    if expected_code == "UNKNOWN_PARAMETER_ERROR":
        expected = (
            "The API returns a parameter validation failure. "
            "The exact parameter error code is not documented in the vendor doc.\n"
            f"{error_response}"
        )
    else:
        expected = (
            f"The API returns a parameter validation error with error code {expected_code}.\n"
            f"{error_response}"
        )
    return {
        "step": f"{title}\n{request_line}",
        "expected": expected,
    }


def _success_step_case(title: str, request_line: str, success_response: str) -> dict[str, str]:
    return {
        "step": f"{title}\n{request_line}",
        "expected": f"The API returns successful response.\n{success_response}",
    }


def _normal_request_value(endpoint: dict[str, Any], parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", ""))
    example = endpoint.get("request_example")
    value = _find_example_value(example, name)
    if value is not None:
        return json.dumps(value, ensure_ascii=False)
    return _sample_value(parameter)


def _find_example_value(data: Any, name: str) -> Any:
    if not name:
        return None
    path_value = _find_example_path_value(data, name)
    if path_value is not None:
        return path_value
    if isinstance(data, dict):
        if name in data:
            return data[name]
        for value in data.values():
            found = _find_example_value(value, name)
            if found is not None:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_example_value(item, name)
            if found is not None:
                return found
    return None


def _find_example_path_value(data: Any, name: str) -> Any:
    parts = [part for part in str(name).split("/") if part]
    if len(parts) <= 1:
        return None
    current = data
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list):
            dict_items = [item for item in current if isinstance(item, dict)]
            if not dict_items:
                return None
            current = dict_items[0]
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def _expected_error_response(
    endpoint: dict[str, Any], expected_error: dict[str, Any]
) -> dict[str, Any]:
    error = endpoint.get("error_response_example")
    code = expected_error.get("code", "ERROR")
    message = expected_error.get("description") or "Parameter validation error"
    if isinstance(error, dict) and error:
        patched = deepcopy(error)
        patched["timestamp"] = _current_unix_timestamp()
        patched.setdefault("error", {})
        if isinstance(patched["error"], dict):
            patched["error"]["code"] = code
            patched["error"]["message"] = message
        return patched
    return {
        "result": "ERROR",
        "timestamp": _current_unix_timestamp(),
        "error": {
            "code": code,
            "message": message,
        },
    }


def _current_unix_timestamp() -> int:
    return int(time.time())


def _success_response(endpoint: dict[str, Any]) -> dict[str, Any]:
    success = endpoint.get("success_response_example")
    if isinstance(success, dict) and success:
        return success
    return {"result": "OK"}


def _wrong_data_type_request_line(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "parameter"))
    param_type = str(parameter.get("type", "")).lower()
    if _is_string_type(param_type):
        return f'"{name}": 123'
    if _is_numeric_type(param_type) or "bool" in param_type:
        return f'"{name}": "test"'
    return f'"{name}": 123'


def _space_request_line(endpoint: dict[str, Any], parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "parameter"))
    normal = _normal_request_value(endpoint, parameter)
    try:
        value = json.loads(normal)
    except json.JSONDecodeError:
        value = normal.strip('"')
    return f'"{name}": " {value} "'


def _is_timestamp_parameter(parameter: dict[str, Any]) -> bool:
    name = str(parameter.get("name", "")).lower()
    description = str(parameter.get("description", "")).lower()
    return "timestamp" in name or name == "time" or "unix time" in description or "timestamp" in description


def _is_array_parameter(parameter: dict[str, Any]) -> bool:
    param_type = str(parameter.get("type", "")).lower()
    return "array" in param_type or "list" in param_type


def _is_optional_parameter(parameter: dict[str, Any]) -> bool:
    required = str(parameter.get("required", "")).strip().upper()
    return required in {"N", "NO", "FALSE", "0", "OPTIONAL"} or required.startswith("N ")


def _is_string_type(param_type: str) -> bool:
    return "string" in param_type or "uuid" in param_type


def _is_numeric_type(param_type: str) -> bool:
    return any(token in param_type for token in ("int", "long", "float", "decimal", "number", "double"))


def _is_player_name_parameter(parameter_name: str) -> bool:
    normalized = "".join(ch for ch in parameter_name.lower() if ch.isalnum())
    exact_names = {
        "userid",
        "username",
        "user",
        "playerid",
        "playername",
        "player",
        "memberid",
        "membername",
        "account",
        "accountid",
        "accountname",
        "loginname",
    }
    if normalized in exact_names:
        return True
    player_terms = ("player", "user", "member", "account", "login")
    name_terms = ("name", "id")
    return any(term in normalized for term in player_terms) and any(
        term in normalized for term in name_terms
    )


def _endpoint_display_name(endpoint_path: str) -> str:
    text = str(endpoint_path or "").strip().rstrip("/")
    if not text:
        return "unknown"
    return text.rsplit("/", 1)[-1] or text


def _sample_request(parameters: list[dict[str, Any]], focus_parameter: str) -> str:
    lines = ["{"]
    for index, parameter in enumerate(parameters):
        name = parameter.get("name", f"parameter{index + 1}")
        sample = _sample_value(parameter)
        suffix = "," if index < len(parameters) - 1 else ""
        marker = "  // focus" if name == focus_parameter else ""
        lines.append(f'  "{name}": {sample}{suffix}{marker}')
    lines.append("}")
    return "\n".join(lines)


def _request_payload(endpoint: dict[str, Any], focus_parameter: str) -> str:
    example = endpoint.get("request_example")
    if isinstance(example, dict) and example:
        return _json_block(example, focus_parameter=focus_parameter)
    return _sample_request(endpoint.get("request_parameters", []), focus_parameter)


def _response_payload(endpoint: dict[str, Any]) -> str:
    success = endpoint.get("success_response_example")
    if isinstance(success, dict) and success:
        return _json_block(success)
    return _sample_response(endpoint.get("response_parameters", []))


def _json_block(data: dict[str, Any], focus_parameter: str = "") -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not focus_parameter:
        return text
    lines = []
    focus_name = str(focus_parameter).split("/")[-1]
    needle = f'"{focus_name}":'
    for line in text.splitlines():
        if needle in line:
            line += "  // focus"
        lines.append(line)
    return "\n".join(lines)


def _sample_response(parameters: list[dict[str, Any]]) -> str:
    lines = ["{"]
    for index, parameter in enumerate(parameters):
        name = parameter.get("name", f"field{index + 1}")
        sample = _sample_value(parameter)
        suffix = "," if index < len(parameters) - 1 else ""
        lines.append(f'  "{name}": {sample}{suffix}')
    lines.append("}")
    return "\n".join(lines)


def _sample_value(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "")).lower()
    param_type = str(parameter.get("type", "")).lower()
    description = str(parameter.get("description", "")).lower()
    text = " ".join([name, param_type, description])

    if "amount" in text:
        return "100.0"
    if "balance" in text or "cash" in text or "bonus" in text:
        return "100"
    if "url" in name or "url" in description:
        return '"https://example.com/replay/4330252729"'
    if "numeric string" in param_type:
        return '"10"'
    if name.endswith("id") or " identifier" in description or " id" in description:
        return f'"{parameter.get("name", "id")}_001"'
    if "timestamp" in text or "time" in text:
        return "1786335355774"
    if "int" in param_type or "long" in param_type or "decimal" in param_type:
        return "1"
    if "bool" in param_type:
        return "true"
    return f'"sample_{parameter.get("name", "value")}"'
