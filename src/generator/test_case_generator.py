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
    PRECONDITIONS_LABEL,
    REMARKS_LABEL,
)
from generator.draft_validator import validate_draft
from generator.reference_selector import selected_categories, select_reference_files
from generator.user_behavior_mapping import (
    MAPPING_CONTRACT_VERSION,
    PLAYER_GAME_STATUS_TITLE_PHRASES,
    SPECIAL_ACCOUNT_TITLE_PHRASES,
    build_user_behavior_mapping_report,
    map_user_behavior_case,
    path_contains_segments,
)
from generator.user_behavior_text_normalizer import normalize_user_behavior_debit_credit_terms
from doc_reader.parameter_dependency import canonical_parameter_path


GENERATED_BY = "deterministic-parameter-generator/v1"
USER_BEHAVIOR_GENERATED_BY = "user-behavior-reference-generator/v1"
VENDOR_TEST_SCENARIO_GENERATED_BY = "vendor-test-scenario-import/v1"
DEPENDENCY_GENERATED_BY = "parameter-dependency-generator/v1"
DEFAULT_MAX_DECIMAL_PLACES = 8

CONFLUENCE_GAME_TYPE_CATEGORIES = {
    "slot game": ("slot_game",),
    "slots": ("slot_game",),
    "mini game (instant win)": ("mini_game", "instant_win"),
    "mini game": ("mini_game",),
    "instant win": ("instant_win",),
    "poker game": ("poker_game",),
    "table game": ("table_game",),
    "live game": ("live_game",),
    "casino live": ("live_game",),
    "arcade": ("arcade_game",),
    "video bingo": ("video_bingo",),
}

UPPERCASE_ACTION_PARAMETER_VALUES = {
    "action": "ACTION",
    "method": "METHOD",
    "operation": "OPERATION",
    "command": "COMMAND",
    "type": "TYPE",
    "requesttype": "REQUESTTYPE",
    "transactiontype": "TRANSACTIONTYPE",
    "subtype": "SUBTYPE",
}

CATEGORY_OUTPUT_PRIORITY = [
    "launch_game",
    "balance",
    "bet",
    "settlement",
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
    "instant_win",
    "poker_game",
    "table_game",
    "video_bingo",
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
    draft["user_behavior_mapping_report"] = build_user_behavior_mapping_report(
        xmind_detail_root
    )
    draft["user_behavior_source"] = {
        "directory": str(Path(xmind_detail_root) / "User_Behavior_map"),
        "xmind_sha256": draft["user_behavior_mapping_report"].get(
            "source_xmind_sha256", ""
        ),
        "mapping_contract_version": MAPPING_CONTRACT_VERSION,
    }
    user_behavior_cases = _user_behavior_cases(context, xmind_detail_root, categories)
    cases.extend(normalize_user_behavior_debit_credit_terms(context, user_behavior_cases))

    if include_parameter_validation:
        cases.extend(_parameter_validation_cases(context, references))

    vendor_cases = _vendor_test_scenario_cases(context)
    cases.extend(normalize_user_behavior_debit_credit_terms(context, vendor_cases))

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
                in {
                    GENERATED_BY,
                    USER_BEHAVIOR_GENERATED_BY,
                    VENDOR_TEST_SCENARIO_GENERATED_BY,
                    DEPENDENCY_GENERATED_BY,
                }
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
    confluence_categories = _confluence_game_type_categories(context)
    if confluence_categories is not None:
        return sorted(confluence_categories)

    # Backward compatibility for details generated before per-item Confluence
    # checkbox states were exported. Once selected_values is present it is the
    # authoritative source and this game-code inference is not used.
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
        if "instant" in text:
            categories.add("instant_win")
        if "poker" in text:
            categories.add("poker_game")
        if "table" in text:
            categories.add("table_game")
        if "bingo" in text:
            categories.add("video_bingo")
    return sorted(categories)


def _confluence_game_type_categories(
    context: dict[str, Any],
) -> set[str] | None:
    profile = context.get("capability_profile", {})
    for item in profile.get("vendor_master_checklist", []):
        if not isinstance(item, dict):
            continue
        if " ".join(str(item.get("name", "")).casefold().split()) != "game type":
            continue
        selected_values = item.get("selected_values")
        if not isinstance(selected_values, list):
            return None
        categories: set[str] = set()
        for value in selected_values:
            normalized = " ".join(str(value).casefold().split())
            categories.update(CONFLUENCE_GAME_TYPE_CATEGORIES.get(normalized, ()))
        return categories
    return None


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
                mapped_case = _user_behavior_case(
                    context, category, reference_case, str(module_path)
                )
                if mapped_case is not None:
                    cases.append(mapped_case)
    return cases


def _user_behavior_selectors(
    category: str, selected_categories: set[str]
) -> list[tuple[str, str]]:
    if category == "launch_game":
        return [("launch_game", "Mandatory > launch game")]
    if category == "balance":
        return [("get_player_balance", "Mandatory > get player balance")]
    if category in {"bet", "settlement"}:
        return [("bet_and_settle", "Mandatory > bet and settle")]
    if category == "amount_precision":
        return []
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
        return [
            ("bet_and_settle", "Multiple Bets > one_bet_endpoint"),
            ("bet_and_settle", "Vendor specific cases > Multiple Bets > one_bet_endpoint"),
        ]
    if category == "multiple_bets_two_bet_endpoint":
        return [
            ("bet_and_settle", "Multiple Bets > two_bet_endpoint"),
            ("bet_and_settle", "Vendor specific cases > Multiple Bets > two_bet_endpoint"),
        ]
    if category == "multiple_settlements_has_round_end_control_parameter":
        return [
            ("bet_and_settle", "Multiple Settlement > Has round-end control parameter"),
            ("debit_and_credit", "Multiple Settlement > Has round-end control parameter"),
        ]
    if category == "multiple_settlements_no_round_end_control_parameter":
        return [("bet_and_settle", "Multiple Settlement > No round-end control parameter")]
    if category in {"rollback_bet", "rollback_settled_bet"}:
        return [
            ("cancel_bet", "rollback_by_bet"),
            ("rollback", "rollback_by_round"),
        ]
    if category == "modify_settlement_adjustment":
        return [
            ("bet_and_settle", "modify_settlement_adjustment"),
            ("cancel_bet", "modify_settlement_adjustment"),
        ]
    if category == "freespin":
        return [("bet_and_settle", "FreeSpin")]
    if category == "jackpot":
        return [("bet_and_settle", "jackpot")]
    if category == "idempotency":
        return [("bet_and_settle", "idempotency")]
    if category == "slot_game":
        return [("slot_game", "Game category > Slot game")]
    if category == "live_game":
        return [("live_game", "Game category > Live game")]
    if category == "arcade_game":
        return [("mini_game", "Game category > Mini game")]
    if category == "mini_game":
        return [("mini_game", "Game category > Mini game")]
    if category == "instant_win":
        return [("instant_win", "Game category > Instant Win")]
    if category == "poker_game":
        return [("poker_game", "Game category > Poker game")]
    if category == "table_game":
        return [("table_game", "Game category > Table game")]
    if category == "video_bingo":
        return [("video_bingo", "Game category > Video Bingo")]
    return []


def _load_reference_module_cases(module_path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(module_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cases = payload.get("cases", [])
    return [case for case in cases if isinstance(case, dict)]


def _path_matches(path: str, fragment: str) -> bool:
    parts = tuple(
        part.strip().casefold() for part in str(path).split(">") if part.strip()
    )
    if "special test cases" in parts:
        return False
    return path_contains_segments(path, fragment)


def _normalize_reference_path(value: str) -> str:
    return " > ".join(part.strip().lower() for part in str(value).split(">") if part.strip())


def _user_behavior_case(
    context: dict[str, Any],
    category: str,
    reference_case: dict[str, Any],
    module_path: str,
) -> dict[str, Any] | None:
    case_category = _user_behavior_case_category(category, reference_case)
    decision = map_user_behavior_case(case_category, reference_case)
    if decision.status != "mapped" or not decision.output_section:
        return None
    output_section = decision.output_section
    scenario = _adapt_behavior_text(context, str(reference_case.get("scenario", "")))
    case = {
        "output_section": output_section,
        "module": _behavior_module(output_section, reference_case),
        "category": case_category,
        "scenario": scenario,
        "preconditions": _behavior_preconditions(context, case_category),
        "steps": _behavior_steps(context, reference_case),
        "remarks": _behavior_remarks(context, case_category),
        "tags": list(reference_case.get("tags", [])),
        "priority": reference_case.get("priority", "P2"),
        "source_reference": {
            "generated_by": USER_BEHAVIOR_GENERATED_BY,
            "source_case_id": reference_case.get("id", ""),
            "source_module": reference_case.get("module", ""),
            "source_path": reference_case.get("path", ""),
            "mapping_rule_id": decision.rule_id,
            "mapping_status": decision.status,
            "xmind_reference_cases": [module_path],
        },
        "unresolved_questions": [],
    }
    case["expected_error"] = _behavior_expected_error(context)
    return case


def _user_behavior_case_category(
    selected_category: str, reference_case: dict[str, Any]
) -> str:
    if selected_category == "modify_settlement_adjustment":
        source_module = str(reference_case.get("module", "")).strip().lower()
        if source_module == "cancel bet":
            return "cancel_settlement_adjustment"
    return selected_category


def _user_behavior_output_section(
    category: str, reference_case: dict[str, Any]
) -> str:
    """Return the canonical output path, or an empty string when not mapped."""
    decision = map_user_behavior_case(category, reference_case)
    return decision.output_section or ""


def _user_behavior_title_subcategory(reference_case: dict[str, Any]) -> str:
    """Route special-account and status cases using their case title."""
    title = str(
        reference_case.get("scenario")
        or reference_case.get("title")
        or reference_case.get("child_topic")
        or ""
    )
    normalized_title = " ".join(title.casefold().split())
    if any(phrase in normalized_title for phrase in SPECIAL_ACCOUNT_TITLE_PHRASES):
        return "Special accounts"
    if any(phrase in normalized_title for phrase in PLAYER_GAME_STATUS_TITLE_PHRASES):
        return "Player / Game status"
    return ""


def _behavior_module(output_section: str, reference_case: dict[str, Any]) -> str:
    leaf = output_section.split(">")[-1].strip()
    if " > Game type > Game category > " in output_section:
        return leaf
    if leaf in {
        "Main flow",
        "Bet config",
        "Settle config",
        "BetAndSettle config",
        "Cancel config",
        "Special accounts",
        "Player / Game status",
    }:
        return leaf
    return str(reference_case.get("module") or output_section.split(">")[-1].strip())


def _parameter_title_behavior_category(_title: str) -> str:
    """Reserved hook for future parameter-title-derived behavior cases.

    Parameter validation cases remain under API parameter test for now. Future
    derivation can map freespin/jackpot/adjust titles into the fixed User
    Behavior branches without changing the routing contract introduced here.
    """
    return ""


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
        "bet": ["bet", "combined_bet_settlement"],
        "amount_precision": ["bet"],
        "multiple_bets": ["bet"],
        "multiple_bets_one_bet_endpoint": ["bet"],
        "multiple_bets_two_bet_endpoint": ["bet"],
        "settlement": ["settlement", "combined_bet_settlement"],
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
        "cancel_settlement_adjustment": ["cancel_bet", "rollback", "settlement"],
        "freespin": ["settlement", "combined_bet_settlement"],
        "jackpot": ["settlement", "combined_bet_settlement"],
        "idempotency": ["settlement", "bet", "combined_bet_settlement"],
        "slot_game": ["bet", "combined_bet_settlement", "settlement"],
        "live_game": ["bet", "combined_bet_settlement", "settlement"],
        "arcade_game": ["bet", "combined_bet_settlement", "settlement"],
        "mini_game": ["bet", "combined_bet_settlement", "settlement"],
        "instant_win": ["bet", "combined_bet_settlement", "settlement"],
        "poker_game": ["bet", "combined_bet_settlement", "settlement"],
        "table_game": ["bet", "combined_bet_settlement", "settlement"],
        "video_bingo": ["bet", "combined_bet_settlement", "settlement"],
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
    for endpoint in _parameter_validation_endpoints(context):
        endpoint_name = endpoint.get("endpoint", "")
        if not endpoint_name:
            continue
        path_parameters = _path_parameters(endpoint)
        path_parameter_names = {
            canonical_parameter_path(parameter.get("name", ""))
            for parameter in path_parameters
        }
        for parameter in path_parameters:
            cases.append(_parameter_case(context, endpoint, parameter, reference_files))
        dependency_enabled = bool(endpoint.get("parameter_dependency"))
        dependency_rules = endpoint.get("parameter_dependencies", []) if dependency_enabled else []
        affected = {
            canonical_parameter_path(value)
            for value in endpoint.get("dependency_affected_parameters", [])
        }
        for parameter in _expanded_request_parameters(endpoint):
            parameter_name = parameter.get("name", "")
            if not parameter_name:
                continue
            if canonical_parameter_path(parameter_name) in path_parameter_names:
                continue
            if dependency_enabled and canonical_parameter_path(parameter_name) in affected:
                continue
            cases.append(_parameter_case(context, endpoint, parameter, reference_files))
        if dependency_enabled:
            if not isinstance(dependency_rules, list) or not dependency_rules:
                raise ValueError(
                    f"Dependency endpoint {endpoint_name!r} is enabled but contains no rules."
                )
            cases.extend(
                _dependency_contextual_parameter_cases(
                    context, endpoint, dependency_rules, reference_files
                )
            )
    return cases


def _parameter_validation_endpoints(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand operation-specific parameter tables into generation endpoints."""
    output: list[dict[str, Any]] = []
    for endpoint in context.get("endpoint_roles", []):
        if not isinstance(endpoint, dict):
            continue
        variants = [
            variant
            for variant in endpoint.get("operation_variants", [])
            if isinstance(variant, dict) and variant.get("request_parameters")
        ]
        if not variants:
            output.append(endpoint)
            continue

        endpoint_name = str(endpoint.get("endpoint", ""))
        endpoint_display_name = _endpoint_display_name(endpoint_name)
        for variant in variants:
            expanded = deepcopy(endpoint)
            for key in (
                "method",
                "request_parameters",
                "response_parameters",
                "request_example",
                "success_response_example",
                "error_response_example",
            ):
                if key in variant:
                    expanded[key] = deepcopy(variant[key])
            operation = str(variant.get("operation", "")).strip()
            expanded["endpoint_operation"] = operation
            expanded["endpoint_name"] = (
                f"{endpoint_display_name} - {operation}"
                if operation
                else endpoint_display_name
            )
            output.append(expanded)
    return output


def _dependency_contextual_parameter_cases(
    context: dict[str, Any],
    endpoint: dict[str, Any],
    rules: list[dict[str, Any]],
    reference_files: list[str],
) -> list[dict[str, Any]]:
    """Apply existing parameter step functions inside each dependency context."""
    parameters = {
        canonical_parameter_path(parameter.get("name", "")): parameter
        for parameter in _expanded_request_parameters(endpoint)
        if isinstance(parameter, dict)
    }
    output: list[dict[str, Any]] = []
    for rule in rules:
        field = str(rule.get("affected_field", ""))
        parameter = parameters.get(canonical_parameter_path(field))
        if not parameter:
            raise ValueError(
                f"Dependency affected field {field!r} is missing from expanded request parameters."
            )
        state = str(rule.get("field_state", ""))
        condition = rule.get("when", {}) if isinstance(rule.get("when"), dict) else {}
        condition_text = _dependency_condition_text(condition)
        expected_error = {
            "code": str(rule.get("error_code", "")),
            "source": "dependency_remark",
            "description": f"Explicit dependency rule {rule.get('rule_id', '')}",
        }
        expected_error["response_json"] = _expected_error_response(
            context, endpoint, expected_error
        )
        contextual_parameter = dict(parameter)
        if state == "required":
            contextual_parameter["required"] = "Y"
            case_kind = "required_validation"
            steps = _parameter_steps(
                context, endpoint, contextual_parameter, expected_error
            )
        elif state == "optional":
            contextual_parameter["required"] = "N"
            case_kind = "optional_validation"
            steps = _optional_parameter_steps(
                context, endpoint, contextual_parameter
            )
        elif state == "forbidden":
            case_kind = "forbidden_validation"
            steps = [
                _step_case(
                    f"{field} set when it must be omitted",
                    _dependency_request_line(
                        field, _dependency_normal_request_value(endpoint, field)
                    ),
                    _required_parameter_error_code(expected_error),
                    _json_block(expected_error["response_json"]),
                )
            ]
        else:
            raise ValueError(
                f"Unsupported dependency field state {state!r} for {field!r}."
            )

        steps = [_format_dependency_step_payload(step, field) for step in steps]
        constraint = rule.get("value_constraint")
        if isinstance(constraint, dict):
            invalid = _invalid_constraint_value(constraint)
            steps.append(
                _step_case(
                    f"{field} violates documented value constraint",
                    _dependency_request_line(
                        field, json.dumps(invalid, ensure_ascii=False)
                    ),
                    _required_parameter_error_code(expected_error),
                    _json_block(expected_error["response_json"]),
                )
            )

        case = _parameter_case(
            context, endpoint, contextual_parameter, reference_files
        )
        case.update(
            {
                "category": "parameter_dependency_validation",
                "scenario": f"case：check the {field} validation when {condition_text}",
                "parameter": field,
                "dependency_rule_id": str(rule.get("rule_id", "")),
                "dependency_case_kind": case_kind,
                "dependency_context": condition,
                "dependency_mutation": {
                    "operation": "apply_existing_parameter_validation",
                    "field": field,
                    "field_state": state,
                },
                "steps": steps,
                "expected_error": expected_error,
                "tags": ["parameter_dependency", case_kind],
                "priority": "P1",
                "source_reference": {
                    "generated_by": DEPENDENCY_GENERATED_BY,
                    "vendor_doc": [str(endpoint.get("endpoint", ""))],
                    "dependency_rule_id": str(rule.get("rule_id", "")),
                    "source_evidence": rule.get("source_evidence", {}),
                    "xmind_reference_cases": reference_files,
                },
            }
        )
        case["remarks"] += (
            f"\nDependency rule: {rule.get('rule_id', '')}; "
            f"{condition_text} => {state}."
        )
        output.append(case)
    return output


def _dependency_condition_text(condition: dict[str, Any]) -> str:
    field = str(condition.get("field", ""))
    operator = str(condition.get("operator", ""))
    if operator == "eq":
        return f"{field}={condition.get('value')}"
    if operator == "in":
        return f"{field} in [{', '.join(str(v) for v in condition.get('values', []))}]"
    if operator == "otherwise":
        return f"{field}=otherwise"
    return f"{field} {operator}".strip()


def _dependency_normal_request_value(endpoint: dict[str, Any], field: str) -> str:
    parameter = next(
        (
            item
            for item in _expanded_request_parameters(endpoint)
            if canonical_parameter_path(item.get("name", ""))
            == canonical_parameter_path(field)
        ),
        {"name": field},
    )
    value = _find_example_value(
        endpoint.get("request_example"), str(parameter.get("name", field))
    )
    if value is not None:
        return json.dumps(value, ensure_ascii=False)
    if _is_object_parameter(parameter):
        payload: dict[str, Any] = {}
        prefix = canonical_parameter_path(field) + "."
        for child in endpoint.get("request_parameters", []):
            child_path = canonical_parameter_path(child.get("name", ""))
            if not child_path.startswith(prefix):
                continue
            relative = child_path[len(prefix):].split(".")
            raw_value = (
                '"EUR"'
                if _dependency_leaf_name(child_path) == "currency"
                else "{}"
                if _is_object_parameter(child)
                else _sample_value(child)
            )
            try:
                child_value = json.loads(raw_value)
            except json.JSONDecodeError:
                child_value = raw_value.strip('"')
            _set_nested_value(payload, relative, child_value)
        return json.dumps(payload or {}, ensure_ascii=False)
    if _dependency_leaf_name(field) == "currency":
        return '"EUR"'
    return _sample_value(parameter)


def _set_nested_value(payload: dict[str, Any], path: list[str], value: Any) -> None:
    current = payload
    for part in path[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    if path:
        current[path[-1]] = value


def _dependency_request_line(
    field: str, value_json: str, commented: bool = False
) -> str:
    parts = canonical_parameter_path(field).split(".")
    try:
        value: Any = json.loads(value_json)
    except json.JSONDecodeError:
        value = value_json.strip('"')
    nested = value
    for part in reversed(parts[1:]):
        nested = {part: nested}
    prefix = "// " if commented else ""
    return f'{prefix}"{parts[0]}": {json.dumps(nested, ensure_ascii=False)}'


def _format_dependency_step_payload(
    step: dict[str, str], field: str
) -> dict[str, str]:
    formatted = dict(step)
    text = str(formatted.get("step", ""))
    title, separator, request_line = text.partition("\n")
    if not separator:
        return formatted
    match = re.match(r'(?s)^(//\s*)?"[^"]+"\s*:\s*(.+)$', request_line.strip())
    if not match:
        return formatted
    formatted["step"] = (
        title.replace("/", ".")
        + "\n"
        + _dependency_request_line(
            field, match.group(2), commented=bool(match.group(1))
        )
    )
    return formatted


def _dependency_leaf_name(value: str) -> str:
    path = canonical_parameter_path(value)
    return path.rsplit(".", 1)[-1].lower()


def _invalid_constraint_value(constraint: dict[str, Any]) -> Any:
    operator = str(constraint.get("operator", ""))
    value = constraint.get("value")
    if operator == "=":
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return value + 1
        return f"invalid-{value}"
    if operator in {">", ">="} and isinstance(value, (int, float)):
        return value - 1 if operator == ">=" else value
    if operator in {"<", "<="} and isinstance(value, (int, float)):
        return value + 1 if operator == "<=" else value
    return "invalid"


def _vendor_test_scenario_cases(context: dict[str, Any]) -> list[dict[str, Any]]:
    if str(context.get("vendor", "")) != "SoftGaming":
        return []
    path = _vendor_test_scenarios_path(context)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    raw_cases = data.get("cases", []) if isinstance(data, dict) else []
    if not isinstance(raw_cases, list):
        return []

    endpoint_index = _endpoint_index(context)
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(raw_cases, start=1):
        if not isinstance(item, dict):
            continue
        draft_case = item.get("draft_case", {})
        if not isinstance(draft_case, dict):
            continue
        case = deepcopy(draft_case)
        output_section = str(
            case.get("output_section") or item.get("output_section") or "User Behavior > Bet and Settle"
        )
        if output_section == API_PARAMETER_TEST_SECTION:
            continue
        endpoint_name = str(case.get("endpoint") or item.get("endpoint") or "").strip()
        endpoint = endpoint_index.get(endpoint_name) or _minimal_endpoint(endpoint_name)
        parameter_name = str(case.get("parameter") or item.get("parameter") or "").strip()

        case["id"] = str(case.get("id") or f"vendor-scenario-{index:02d}")
        case["output_section"] = output_section
        case["category"] = str(case.get("category") or item.get("category") or "vendor_provided")
        case["scenario"] = str(case.get("scenario") or item.get("title") or f"Vendor scenario {index}")
        case["module"] = str(case.get("module") or item.get("module") or _endpoint_display_name(endpoint_name))
        case["endpoint"] = endpoint_name
        case["endpoint_name"] = str(case.get("endpoint_name") or _endpoint_display_name(endpoint_name))
        case["endpoint_group"] = str(case.get("endpoint_group") or endpoint.get("role", ""))
        case["endpoints"] = case.get("endpoints") or ([endpoint_name] if endpoint_name else [])
        case["parameter"] = parameter_name
        case["preconditions"] = _preconditions(context, endpoint)
        case["remarks"] = _remarks(endpoint, {"name": parameter_name})
        case["tags"] = _vendor_case_tags(case)
        case["priority"] = str(case.get("priority") or "P2")
        case["source_reference"] = _vendor_case_source_reference(case, item, path)
        case["unresolved_questions"] = case.get("unresolved_questions") or []
        if _vendor_case_looks_negative(case) and not case.get("expected_error"):
            case["expected_error"] = deepcopy(context.get("parameter_error", {}))
        cases.append(case)
    return cases


def _vendor_test_scenarios_path(context: dict[str, Any]) -> Path:
    source_files = context.get("source_files", {})
    vendor_detail = ""
    if isinstance(source_files, dict):
        vendor_detail = str(source_files.get("vendor_detail", ""))
    if vendor_detail:
        return Path(vendor_detail) / "vendor_test_scenarios.json"
    vendor = str(context.get("vendor", ""))
    return Path("new_vendor_detail") / vendor / "vendor_test_scenarios.json"


def _endpoint_index(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    endpoints: dict[str, dict[str, Any]] = {}
    for endpoint in context.get("endpoint_roles", []):
        if not isinstance(endpoint, dict):
            continue
        name = str(endpoint.get("endpoint", "")).strip()
        if name:
            endpoints[name] = endpoint
    return endpoints


def _minimal_endpoint(endpoint_name: str) -> dict[str, Any]:
    return {
        "endpoint": endpoint_name,
        "role": "",
        "request_example": {},
        "success_response_example": {},
        "error_response_example": {},
    }


def _vendor_case_tags(case: dict[str, Any]) -> list[str]:
    tags = case.get("tags", [])
    output = [str(tag) for tag in tags] if isinstance(tags, list) else []
    return _merge_unique(output, ["vendor_provided"])


def _vendor_case_source_reference(
    case: dict[str, Any], item: dict[str, Any], path: Path
) -> dict[str, Any]:
    source = case.get("source_reference", {})
    if not isinstance(source, dict):
        source = {}
    source.setdefault("generated_by", VENDOR_TEST_SCENARIO_GENERATED_BY)
    source.setdefault("vendor_test_scenarios", str(path))
    for key in ("source_file", "source_run", "source_test_number", "source_anchor"):
        value = item.get(key)
        if value not in (None, ""):
            source.setdefault(key, value)
    return source


def _vendor_case_looks_negative(case: dict[str, Any]) -> bool:
    fields = [
        case.get("category", ""),
        case.get("scenario", ""),
        case.get("preconditions", ""),
        case.get("remarks", ""),
    ]
    for step in case.get("steps", []) or []:
        if isinstance(step, dict):
            fields.append(step.get("step", ""))
            fields.append(step.get("expected", ""))
    text = "\n".join(str(field).lower() for field in fields)
    return any(
        keyword in text
        for keyword in (
            "fail",
            "failed",
            "failure",
            "reject",
            "error",
            "invalid",
            "wrong",
            "duplicate",
            "negative",
            "失败",
            "錯誤",
            "错误",
        )
    )


def _merge_unique(primary: list[Any], extra: list[Any]) -> list[Any]:
    output: list[Any] = []
    for item in primary + extra:
        if item not in output:
            output.append(item)
    return output


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
    enriched_parameters = _sort_parameters_by_request_example(endpoint, enriched_parameters)
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


def _sort_parameters_by_request_example(
    endpoint: dict[str, Any], parameters: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    order = _request_example_key_order(endpoint.get("request_example"))
    if not order:
        return parameters
    order_index = {name.lower(): index for index, name in enumerate(order)}
    return [
        parameter
        for _, parameter in sorted(
            enumerate(parameters),
            key=lambda item: (
                order_index.get(
                    str(item[1].get("name", "")).strip().lower(),
                    len(order_index) + item[0],
                ),
                item[0],
            ),
        )
    ]


def _request_example_key_order(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [str(key) for key in value.keys()]


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
    endpoint_display_name = str(
        endpoint.get("endpoint_name") or _endpoint_display_name(endpoint_name)
    )
    endpoint_operation = str(endpoint.get("endpoint_operation", "")).strip()
    parameter_name = parameter.get("name", "")
    scenario = API_PARAMETER_CASE_TITLE_TEMPLATE.format(parameter=parameter_name)
    expected_error = _expected_error_for_parameter(context, parameter)
    expected_error["response_json"] = _expected_error_response(
        context, endpoint, expected_error
    )
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
        "endpoint_operation": endpoint_operation,
        "endpoints": [endpoint_name],
        "parameter": parameter_name,
        "preconditions": _preconditions(context, endpoint),
        "steps": _parameter_steps(context, endpoint, parameter, expected_error),
        "remarks": _remarks(endpoint, parameter),
        "expected_error": expected_error,
        "tags": ["parameter_validation", "negative"],
        "priority": "P2",
        "source_reference": {
            "generated_by": GENERATED_BY,
            "vendor_doc": [endpoint_name],
            "endpoint_operation": endpoint_operation,
            "xmind_reference_cases": reference_files,
        },
        "unresolved_questions": [],
    }


def _expected_error_for_parameter(
    context: dict[str, Any], parameter: dict[str, Any]
) -> dict[str, Any]:
    if parameter.get("source") == "path_parameter":
        return _path_parameter_error(context, str(parameter.get("name", "")))
    if _is_encryption_parameter(parameter):
        encryption_error = deepcopy(context.get("encryption_error", {}))
        if not encryption_error:
            raise ValueError(
                "No documented encryption/signature validation error code was found."
            )
        return encryption_error
    return deepcopy(context.get("parameter_error", {}))


def _is_encryption_parameter(parameter: dict[str, Any]) -> bool:
    text = f"{parameter.get('name', '')} {parameter.get('description', '')}".lower()
    tokens = set(re.findall(r"[a-z]+", text))
    return bool(tokens & {"hmac", "signature", "sign", "hash", "encrypt", "decrypt"})


def _path_parameter_error(context: dict[str, Any], parameter_name: str) -> dict[str, Any]:
    fallback = deepcopy(context.get("parameter_error", {}))
    fallback.setdefault("applies_to", parameter_name)
    return fallback


def _error_for_keywords(
    context: dict[str, Any], keywords: tuple[str, ...]
) -> dict[str, str] | None:
    for item in context.get("error_codes", []):
        text = " ".join(
            str(item.get(key, "")) for key in ("code", "context", "message", "description")
        ).lower()
        if any(keyword in text for keyword in keywords):
            return {
                "code": str(item.get("code", "")).strip(),
                "source": "documented",
                "description": str(
                    item.get("context") or item.get("message") or item.get("description") or ""
                ),
            }
    return None


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
    request = _request_payload(endpoint)
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
    context: dict[str, Any],
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    expected_error: dict[str, Any],
) -> list[dict[str, str]]:
    parameter_name = str(parameter.get("name", "parameter"))
    lowered = parameter_name.lower()
    leaf_name = _dependency_leaf_name(parameter_name)
    code = _required_parameter_error_code(expected_error)
    error_response = _json_block(_expected_error_response(context, endpoint, expected_error))
    error_label = "encryption/signature validation" if _is_encryption_parameter(parameter) else "parameter validation"
    steps: list[dict[str, str]] = []

    if parameter.get("source") == "path_parameter":
        return _path_parameter_steps(endpoint, parameter, code, error_response)

    if _is_optional_parameter(parameter):
        return _optional_parameter_steps(context, endpoint, parameter)

    if _is_array_parameter(parameter):
        return _array_parameter_steps(endpoint, parameter, code, error_response, error_label)

    if _is_object_parameter(parameter):
        return _object_parameter_steps(endpoint, parameter, code, error_response)

    if lowered in {"hmac", "hash"}:
        return _hash_parameter_steps(endpoint, parameter, code, error_response, error_label)

    if "amount" in leaf_name:
        valid_decimal, invalid_decimal = _amount_decimal_cases(endpoint, parameter)
        success_response = _json_block(_success_response(endpoint))
        steps = [
            _step_case(
                f"{parameter_name} doesn't set",
                f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}',
                code,
                error_response,
            ),
            _step_case(f"{parameter_name} Input blank", f'"{parameter_name}": ""', code, error_response),
            _step_case(
                f"{parameter_name} Input exceed 20 digit numbers",
                _amount_request_line(parameter, "123456789012345678901"),
                code,
                error_response,
            ),
            _success_step_case(
                valid_decimal[0],
                valid_decimal[1],
                success_response,
            ),
            _step_case(
                invalid_decimal[0],
                invalid_decimal[1],
                code,
                error_response,
            ),
            _step_case_for_error(
                f"{parameter_name} Input negative number",
                _amount_request_line(parameter, "-100.0"),
                context,
                endpoint,
                _error_for_keywords(context, ("insufficient funds", "insufficient balance"))
                or expected_error,
            ),
            _step_case(
                f"{parameter_name} Input space",
                _space_request_line(endpoint, parameter),
                code,
                error_response,
            ),
            _step_case(f"{parameter_name} Input string", f'"{parameter_name}": "test"', code, error_response),
        ]
        if _is_rollback_endpoint(endpoint):
            steps.append(
                _success_step_case(
                    f"{parameter_name} Input lower than bet_amount",
                    f'"{parameter_name}": 1',
                    _json_block(_success_response(endpoint)),
                )
            )
        return steps

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

    if leaf_name == "currency":
        steps.append(
            _step_case_for_error(
                f"{parameter_name} Input invalid currency",
                f'"{parameter_name}": "TWD"',
                context,
                endpoint,
                _error_for_keywords(context, ("currency mismatch", "invalid currency")) or expected_error,
            )
        )
    elif _is_timestamp_parameter(parameter):
        steps.append(
            _step_case(
                _wrong_data_type_step_title(parameter),
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
    else:
        steps.append(
            _step_case(
                _wrong_data_type_step_title(parameter),
                _wrong_data_type_request_line(parameter),
                code,
                error_response,
            )
        )

    if lowered == "userid":
        steps.append(
            _step_case("userId input space", '"userId": " playerA "', code, error_response)
        )
    if _is_uppercase_action_parameter(parameter):
        steps.append(
            _step_case(
                f"{parameter_name} input uppercase",
                _uppercase_action_request_line(endpoint, parameter),
                code,
                error_response,
            )
        )
    return steps


def _hash_parameter_steps(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    expected_code: str,
    error_response: str,
    error_label: str = "parameter validation",
) -> list[dict[str, str]]:
    parameter_name = str(parameter.get("name", "hmac"))
    return [
        _step_case(
            f"{parameter_name} doesn't set",
            f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}',
            expected_code,
            error_response, error_label,
        ),
        _step_case(
            f"{parameter_name} leave blank",
            f'"{parameter_name}": ""',
            expected_code,
            error_response, error_label,
        ),
        _step_case(
            f"{parameter_name} input int",
            f'"{parameter_name}": 123',
            expected_code,
            error_response, error_label,
        ),
    ]


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
    context: dict[str, Any],
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
) -> list[dict[str, str]]:
    parameter_name = str(parameter.get("name", "parameter"))
    lowered = parameter_name.lower()
    leaf_name = _dependency_leaf_name(parameter_name)
    if _is_array_parameter(parameter):
        specs = _array_parameter_step_specs(endpoint, parameter)
    elif _is_object_parameter(parameter):
        return _optional_object_parameter_steps(context, endpoint, parameter)
    elif "amount" in leaf_name:
        valid_decimal, invalid_decimal = _amount_decimal_cases(endpoint, parameter)
        success_response = _json_block(_success_response(endpoint))
        steps = [
            _success_step_case(
                f"{parameter_name} doesn't set",
                _optional_amount_missing_request_line(parameter),
                success_response,
            ),
            _success_step_case(f"{parameter_name} Input blank", f'"{parameter_name}": ""', success_response),
            _success_step_case(
                f"{parameter_name} Input exceed 20 digit numbers",
                _amount_request_line(parameter, "123456789012345678901"),
                success_response,
            ),
            _success_step_case(
                valid_decimal[0],
                valid_decimal[1],
                success_response,
            ),
            _step_case_for_error(
                invalid_decimal[0],
                invalid_decimal[1],
                context,
                endpoint,
                context.get("parameter_error", {}),
            ),
            _step_case_for_error(
                f"{parameter_name} Input negative number",
                _amount_request_line(parameter, "-100.0"),
                context,
                endpoint,
                _error_for_keywords(context, ("insufficient funds", "insufficient balance"))
                or context.get("parameter_error", {}),
            ),
            _success_step_case(
                f"{parameter_name} Input space",
                _space_request_line(endpoint, parameter),
                success_response,
            ),
            _success_step_case(f"{parameter_name} Input string", f'"{parameter_name}": "test"', success_response),
        ]
        if _is_rollback_endpoint(endpoint):
            steps.append(
                _success_step_case(
                    f"{parameter_name} Input lower than bet_amount",
                    f'"{parameter_name}": 1',
                    success_response,
                )
            )
        return steps
    else:
        specs = [
            (f"{parameter_name} doesn't set", f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}'),
            (f"{parameter_name} leave blank", f'"{parameter_name}": ""'),
            (f"{parameter_name} input space", _space_request_line(endpoint, parameter)),
            (
                _wrong_data_type_step_title(parameter),
                _wrong_data_type_request_line(parameter),
            ),
        ]
    success_response = _json_block(_success_response(endpoint))
    return [_success_step_case(title, request_line, success_response) for title, request_line in specs]


def _optional_amount_missing_request_line(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "amount")).split("/")[-1] or "amount"
    return f'"{name}": 0'


def _amount_decimal_case(endpoint: dict[str, Any], parameter: dict[str, Any]) -> tuple[str, str]:
    """Return the invalid max+1 decimal boundary for compatibility."""
    return _amount_decimal_cases(endpoint, parameter)[1]


def _amount_decimal_cases(
    endpoint: dict[str, Any], parameter: dict[str, Any]
) -> tuple[tuple[str, str], tuple[str, str]]:
    name = str(parameter.get("name", "amount"))
    max_decimals = _infer_amount_decimal_places(endpoint, parameter)
    valid_value = _decimal_boundary_value(max_decimals)
    invalid_decimals = max_decimals + 1
    invalid_value = _decimal_boundary_value(invalid_decimals)
    return (
        (
            f"{name} Input {max_decimals} decimal numbers",
            _amount_request_line(parameter, valid_value),
        ),
        (
            f"{name} Input {invalid_decimals} decimal numbers",
            _amount_request_line(parameter, invalid_value),
        ),
    )


def _decimal_boundary_value(decimal_places: int) -> str:
    digits = "".join(str((index % 9) + 1) for index in range(decimal_places))
    return f"100.{digits}"


def _amount_request_line(parameter: dict[str, Any], value: str) -> str:
    name = str(parameter.get("name", "amount"))
    return f'"{name}": {_format_amount_value(parameter, value)}'


def _format_amount_value(parameter: dict[str, Any], value: str) -> str:
    parameter_type = str(parameter.get("type", "")).lower()
    return json.dumps(value) if _is_string_type(parameter_type) or "numeric string" in parameter_type else value


def _infer_amount_decimal_places(endpoint: dict[str, Any], parameter: dict[str, Any]) -> int:
    explicit = _explicit_decimal_places_from_text(_amount_precision_text(endpoint, parameter))
    return explicit if explicit is not None else DEFAULT_MAX_DECIMAL_PLACES


def _amount_precision_text(endpoint: dict[str, Any], parameter: dict[str, Any]) -> str:
    pieces = []
    for item in [parameter, *endpoint.get("request_parameters", []), *endpoint.get("response_parameters", [])]:
        if not isinstance(item, dict):
            continue
        item_text = " ".join(str(item.get(field, "")) for field in ("name", "type", "description", "remark", "mapping"))
        if "amount" in item_text.lower() or "balance" in item_text.lower():
            pieces.append(item_text)
    return " ".join(pieces)


def _explicit_decimal_places_from_text(text: str) -> int | None:
    normalized = " ".join(text.lower().split())
    patterns = (
        r"(?:must\s+always\s+have|always\s+have|has|with|up\s+to|maximum(?:\s+of)?|max(?:imum)?)\s+(\d+)\s+(?:digits?\s+after\s+(?:the\s+)?decimal|decimal\s+places?)",
        r"(\d+)\s+(?:digits?\s+after\s+(?:the\s+)?decimal|decimal\s+places?)",
        r"(?:scale|precision)\s*[:=]?\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None


def _array_parameter_steps(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    expected_code: str,
    error_response: str,
    error_label: str = "parameter validation",
) -> list[dict[str, str]]:
    return [
        _step_case(title, request_line, expected_code, error_response, error_label)
        for title, request_line in _array_parameter_step_specs(endpoint, parameter)
    ]


def _object_parameter_steps(
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    expected_code: str,
    error_response: str,
) -> list[dict[str, str]]:
    return [
        _step_case(title, request_line, expected_code, error_response)
        for title, request_line in _object_parameter_step_specs(endpoint, parameter)
    ]


def _optional_object_parameter_steps(
    context: dict[str, Any], endpoint: dict[str, Any], parameter: dict[str, Any]
) -> list[dict[str, str]]:
    specs = _object_parameter_step_specs(endpoint, parameter)
    success_response = _json_block(_success_response(endpoint))
    steps = [_success_step_case(*specs[0], success_response)]
    expected_error = context.get("parameter_error", {})
    expected_code = _required_parameter_error_code(expected_error)
    error_response = _json_block(_expected_error_response(context, endpoint, expected_error))
    steps.extend(
        _step_case(title, request_line, expected_code, error_response)
        for title, request_line in specs[1:]
    )
    return steps


def _object_parameter_step_specs(
    endpoint: dict[str, Any], parameter: dict[str, Any]
) -> list[tuple[str, str]]:
    name = str(parameter.get("name", "parameter"))
    normal = _normal_request_value(endpoint, parameter)
    cases = [
        (f"{name} doesn't set", f'// "{name}": {normal}'),
        (f"{name} input null", f'"{name}": null'),
        (f"{name} input empty object", f'"{name}": {{}}'),
        (f"{name} input array instead of object", f'"{name}": []'),
        (f"{name} input string instead of object", f'"{name}": "test"'),
        (f"{name} input number instead of object", f'"{name}": 123'),
    ]
    for child_name, payload in _object_payloads_missing_required_children(
        endpoint, parameter
    ):
        cases.append(
            (
                f"{name} object missing required field {child_name}",
                f'"{name}": {json.dumps(payload, ensure_ascii=False)}',
            )
        )
    return cases


def _object_payloads_missing_required_children(
    endpoint: dict[str, Any], parameter: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    parent_name = str(parameter.get("name", "")).strip()
    example = _find_example_value(endpoint.get("request_example"), parent_name)
    if not parent_name or not isinstance(example, dict):
        return []
    prefix = f"{parent_name}/"
    output = []
    for child in endpoint.get("request_parameters", []):
        child_name = str(child.get("name", "")).strip()
        if not child_name.startswith(prefix) or not _is_required_parameter(child):
            continue
        relative_path = [part for part in child_name[len(prefix):].split("/") if part]
        payload = deepcopy(example)
        if _remove_object_path(payload, relative_path):
            output.append(("/".join(relative_path), payload))
    return output


def _remove_object_path(payload: dict[str, Any], path: list[str]) -> bool:
    if not path:
        return False
    current: Any = payload
    for part in path[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if not isinstance(current, dict) or path[-1] not in current:
        return False
    del current[path[-1]]
    return True


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
    title: str, request_line: str, expected_code: str, error_response: str,
    error_label: str = "parameter validation",
) -> dict[str, str]:
    response = str(error_response).strip()
    response_text = f"\n{response}" if response and response != "{}" else ""
    expected = (
        f"The API returns a {error_label} error with error code {expected_code}."
        f"{response_text}"
    )
    return {
        "step": f"{title}\n{request_line}",
        "expected": expected,
    }


def _step_case_for_error(
    title: str,
    request_line: str,
    context: dict[str, Any],
    endpoint: dict[str, Any],
    expected_error: dict[str, Any],
) -> dict[str, str]:
    code = _required_parameter_error_code(expected_error)
    return _step_case(
        title,
        request_line,
        code,
        _json_block(_expected_error_response(context, endpoint, expected_error)),
    )


def _required_parameter_error_code(expected_error: dict[str, Any]) -> str:
    code = str(expected_error.get("code", "")).strip()
    if not code:
        raise ValueError("A documented parameter validation error code is required.")
    return code


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
    if _dependency_leaf_name(name) == "currency":
        return '"EUR"'
    if _is_object_parameter(parameter):
        return _dependency_normal_request_value(endpoint, name)
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
    context: dict[str, Any], endpoint: dict[str, Any], expected_error: dict[str, Any]
) -> dict[str, Any]:
    documented_response = expected_error.get("response_json")
    if isinstance(documented_response, dict) and documented_response:
        return deepcopy(documented_response)
    examples = []
    endpoints = [endpoint]
    # A vendor may document one shared error shape for several endpoints. If
    # this endpoint has no example, use a compatible example from the same
    # vendor before falling back to the explicitly documented empty object.
    endpoints.extend(
        item
        for item in context.get("endpoint_roles", [])
        if isinstance(item, dict) and item is not endpoint
    )
    for candidate in endpoints:
        error = candidate.get("error_response_example")
        if isinstance(error, dict) and error:
            examples.append(error)
        # Shared endpoints may carry their actual response examples on
        # operation variants.
        for variant in candidate.get("operation_variants", []):
            if not isinstance(variant, dict):
                continue
            variant_error = variant.get("error_response_example")
            if isinstance(variant_error, dict) and variant_error:
                examples.append(variant_error)

    for error in examples:
        # Vendor docs commonly provide one fixed Error Name example (for
        # example INSUFFICIENT_BALANCE) while the error-code table separately
        # documents the HTTP-level parameter error. Reuse the response shape,
        # but replace the Error Name selected by the parameter-error rule.
        if _is_parameter_validation_error_response(error) or _has_fixed_error_name(error):
            return _replace_error_response_code(error, expected_error)
    return {}


def _replace_error_response_code(template: dict[str, Any], expected_error: dict[str, Any]) -> dict[str, Any]:
    response = deepcopy(template)
    code = str(expected_error.get("code", "")).strip()
    error_name = _parameter_error_name(expected_error)
    if not code and not error_name:
        return response
    key = _error_response_code_key(response)
    if key:
        response[key] = error_name or code
    return response


def _parameter_error_name(expected_error: dict[str, Any]) -> str:
    """Map the selected HTTP parameter error to the documented Error Name."""
    description = str(expected_error.get("description", "")).lower()
    if "invalid request" in description or "missing/invalid parameters" in description:
        return "INVALID_REQUEST"
    if "insufficient balance" in description or "insufficient funds" in description:
        return "INSUFFICIENT_FUNDS"
    return ""


def _has_fixed_error_name(response: dict[str, Any]) -> bool:
    """Return whether the example uses the vendor's uppercase Error Name format."""
    value = response.get("error")
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Z][A-Z0-9_]*", value))


def _error_response_code_key(response: dict[str, Any]) -> str:
    for key in ("error", "message", "code", "error_code", "errorCode"):
        if key in response:
            return key
    return ""


def _is_parameter_validation_error_response(error: dict[str, Any]) -> bool:
    if (
        str(error.get("result", "")).upper() == "ERROR"
        and any(key in error for key in ("code", "error_code", "errorCode"))
    ):
        return True
    message = str(error.get("error") or error.get("message") or error.get("description") or "")
    normalized = message.lower()
    transaction_error_terms = (
        "transaction failed",
        "insufficient funds",
        "insufficient balance",
        "rollback",
        "duplicate",
        "already processed",
    )
    if any(term in normalized for term in transaction_error_terms):
        return False
    parameter_error_terms = (
        "invalid parameter",
        "invalid parameters",
        # A number of vendors describe parameter failures with the concrete
        # field value (for example, "Invalid currency") rather than the word
        # parameter.
        "invalid ",
        "parameter",
        "invalid signature",
        "missing",
        "required",
        "wrong",
    )
    return any(term in normalized for term in parameter_error_terms)


def _success_response(endpoint: dict[str, Any]) -> dict[str, Any]:
    success = endpoint.get("success_response_example")
    if isinstance(success, dict) and success:
        return success
    return {}


def _wrong_data_type_request_line(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "parameter"))
    param_type = str(parameter.get("type", "")).lower()
    if _is_string_type(param_type):
        return f'"{name}": 123'
    if _is_numeric_type(param_type) or "bool" in param_type:
        return f'"{name}": "test"'
    return f'"{name}": 123'


def _wrong_data_type_step_title(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "parameter"))
    param_type = str(parameter.get("type", "")).lower()
    if _is_string_type(param_type):
        return f"{name} input int"
    if _is_numeric_type(param_type) or "bool" in param_type:
        return f"{name} input string"
    return f"{name} input wrong data type"


def _is_rollback_endpoint(endpoint: dict[str, Any]) -> bool:
    role = str(endpoint.get("role", "")).lower()
    path = str(endpoint.get("endpoint", "")).lower()
    return any(term in role for term in ("rollback", "cancel_bet")) or any(
        term in path for term in ("rollback", "refund", "cancel")
    )


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


def _is_object_parameter(parameter: dict[str, Any]) -> bool:
    param_type = str(parameter.get("type", "")).lower()
    return any(token in param_type for token in ("object", "dict", "map"))


def _is_optional_parameter(parameter: dict[str, Any]) -> bool:
    required = str(parameter.get("required", "")).strip().upper()
    return required in {"N", "NO", "FALSE", "0", "OPTIONAL"} or required.startswith("N ")


def _is_required_parameter(parameter: dict[str, Any]) -> bool:
    required = str(parameter.get("required", "")).strip().upper()
    return required in {"Y", "YES", "TRUE", "1", "REQUIRED"} or required.startswith("Y ")


def _is_string_type(param_type: str) -> bool:
    return "string" in param_type or "uuid" in param_type


def _is_numeric_type(param_type: str) -> bool:
    return any(token in param_type for token in ("int", "long", "float", "decimal", "number", "double"))


def _is_uppercase_action_parameter(parameter: dict[str, Any]) -> bool:
    normalized = _normalized_parameter_name(str(parameter.get("name", "")))
    if normalized in UPPERCASE_ACTION_PARAMETER_VALUES:
        return True
    description = str(parameter.get("description", "")).lower()
    return normalized in {"type", "subtype"} and any(
        term in description for term in ("action", "operation", "command")
    )


def _uppercase_action_request_line(endpoint: dict[str, Any], parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "parameter"))
    normalized = _normalized_parameter_name(name)
    normal = _normal_request_value(endpoint, parameter)
    try:
        value = json.loads(normal)
    except json.JSONDecodeError:
        value = normal.strip('"')
    if isinstance(value, str) and value:
        uppercase_value = value.upper()
    else:
        uppercase_value = UPPERCASE_ACTION_PARAMETER_VALUES.get(normalized, "ACTION")
    return f'"{name}": {json.dumps(uppercase_value, ensure_ascii=False)}'


def _normalized_parameter_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _endpoint_display_name(endpoint_path: str) -> str:
    text = str(endpoint_path or "").strip().rstrip("/")
    if not text:
        return "unknown"
    parts = [part for part in text.split("/") if part]
    for part in reversed(parts):
        if not (part.startswith("{") and part.endswith("}")):
            return part
    return parts[-1] if parts else text


def _request_payload(endpoint: dict[str, Any]) -> str:
    example = endpoint.get("request_example")
    if isinstance(example, dict) and example:
        return _json_block(example)
    return _json_block({})


def _response_payload(endpoint: dict[str, Any]) -> str:
    success = endpoint.get("success_response_example")
    if isinstance(success, dict) and success:
        return _json_block(success)
    return _json_block({})


def _json_block(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


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
        return '"https://example.com"'
    if "numeric string" in param_type:
        return '"10"'
    if name.endswith("id") or " identifier" in description or " id" in description:
        return f'"{parameter.get("name", "id")}_001"'
    if "timestamp" in text or "time" in text:
        return str(int(time.time()))
    if "int" in param_type or "long" in param_type or "decimal" in param_type:
        return "1"
    if "bool" in param_type:
        return "true"
    return f'"sample_{parameter.get("name", "value")}"'
