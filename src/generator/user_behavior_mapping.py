"""Canonical User Behavior source-path to XMind output mapping."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


MAPPING_CONTRACT_VERSION = "user-behavior-mapping/v2"

USER_BEHAVIOR_ROOT = "User Behavior"
LAUNCH_GAME_SECTION = f"{USER_BEHAVIOR_ROOT} > Launch Game"
BALANCE_SECTION = f"{USER_BEHAVIOR_ROOT} > Get Player balance"
BET_SETTLE_SECTION = f"{USER_BEHAVIOR_ROOT} > Bet and Settle"
CANCEL_BET_SECTION = f"{USER_BEHAVIOR_ROOT} > Cancel Bet"
DEBIT_CREDIT_SECTION = f"{USER_BEHAVIOR_ROOT} > Debit and Credit"
CANCEL_DEBIT_SECTION = f"{USER_BEHAVIOR_ROOT} > Cancel Debit"

BET_SETTLE_GAME_CATEGORY = f"{BET_SETTLE_SECTION} > Game type > Game category"
BET_SETTLE_MAIN_FLOW = f"{BET_SETTLE_SECTION} > Game type > Main flow"
BET_CONFIG_SECTION = f"{BET_SETTLE_SECTION} > Bet config"
SETTLE_CONFIG_SECTION = f"{BET_SETTLE_SECTION} > Settle config"
BET_AND_SETTLE_CONFIG_SECTION = f"{BET_SETTLE_SECTION} > BetAndSettle config"
BET_SETTLE_SPECIAL_ACCOUNTS = f"{BET_SETTLE_SECTION} > Special accounts"
BET_SETTLE_STATUS = f"{BET_SETTLE_SECTION} > Player / Game status"

CANCEL_MAIN_FLOW = f"{CANCEL_BET_SECTION} > Main flow"
CANCEL_CONFIG_SECTION = f"{CANCEL_BET_SECTION} > Cancel config"
CANCEL_SPECIAL_ACCOUNTS = f"{CANCEL_BET_SECTION} > Special accounts"
CANCEL_STATUS = f"{CANCEL_BET_SECTION} > Player / Game status"

GAME_CATEGORY_MODULES = {
    "instant win": "Instant Win",
    "live game": "Live game",
    "mini game": "Mini game",
    "poker game": "Poker game",
    "slot game": "Slot game",
    "table game": "Table game",
    "video bingo": "Video Bingo",
}

GAME_CATEGORY_SECTIONS = {
    f"{BET_SETTLE_GAME_CATEGORY} > {title}"
    for title in GAME_CATEGORY_MODULES.values()
}

CANONICAL_USER_BEHAVIOR_LEAF_SECTIONS = {
    LAUNCH_GAME_SECTION,
    BALANCE_SECTION,
    BET_SETTLE_MAIN_FLOW,
    BET_CONFIG_SECTION,
    SETTLE_CONFIG_SECTION,
    BET_AND_SETTLE_CONFIG_SECTION,
    BET_SETTLE_SPECIAL_ACCOUNTS,
    BET_SETTLE_STATUS,
    CANCEL_MAIN_FLOW,
    CANCEL_CONFIG_SECTION,
    CANCEL_SPECIAL_ACCOUNTS,
    CANCEL_STATUS,
    *GAME_CATEGORY_SECTIONS,
}

LEGACY_FORBIDDEN_BRANCHES = (
    "Jackpot / FreeSpin",
    "Adjustment",
    "Vendor specific cases",
)

SPECIAL_ACCOUNT_TITLE_PHRASES = (
    "timeout player",
    "timeout user",
    "error player",
    "error user",
    "result0 player",
    "result0 user",
    "refund0 player",
    "refund0 user",
    "cancel player",
    "cancel user",
    "delay10s player",
    "delay10s user",
)

PLAYER_GAME_STATUS_TITLE_PHRASES = (
    "game status is abnormal",
    "player status is abnormal",
    "game status is abnornal",
    "player status is abnornal",
)

MAPPING_RULE_IDS = {
    "excluded.special_test_cases",
    "direct.launch_game",
    "direct.balance",
    "direct.authenticate",
    "game_category.module",
    "bet.main_flow",
    "bet.bet_config",
    "bet.settle_config",
    "bet.bet_and_settle_config",
    "bet.special_accounts",
    "bet.player_game_status",
    "bet.authentication_required",
    "cancel.main_flow",
    "cancel.cancel_config",
    "cancel.special_accounts",
    "cancel.player_game_status",
    "legacy.title_special_accounts",
    "legacy.title_player_game_status",
    "fallback.freespin_jackpot_main_flow",
    "fallback.adjustment_config",
    "fallback.rollback_config",
    "unmapped.no_rule",
}

KNOWLEDGE_CATEGORY_TO_XMIND_SECTION = {
    "parameter_validation": "API parameter test",
    "parameter_dependency_validation": "API parameter test",
    "amount_precision": "API parameter test",
    "launch_game": LAUNCH_GAME_SECTION,
    "authenticate": LAUNCH_GAME_SECTION,
    "authentication_is_necessary": BET_SETTLE_SECTION,
    "balance": BALANCE_SECTION,
    "bet": BET_SETTLE_SECTION,
    "settlement": BET_SETTLE_SECTION,
    "multiple_bets": BET_SETTLE_SECTION,
    "multiple_bets_one_bet_endpoint": BET_SETTLE_SECTION,
    "multiple_bets_two_bet_endpoint": BET_SETTLE_SECTION,
    "multiple_settlements": BET_SETTLE_SECTION,
    "multiple_settlements_has_round_end_control_parameter": BET_SETTLE_SECTION,
    "multiple_settlements_no_round_end_control_parameter": BET_SETTLE_SECTION,
    "modify_settlement_adjustment": BET_SETTLE_SECTION,
    "cancel_settlement_adjustment": CANCEL_BET_SECTION,
    "settle_by_round_or_settle_by_bet": BET_SETTLE_SECTION,
    "bet_and_settle": BET_SETTLE_SECTION,
    "bet_and_settle_has_round_end_control_parameter": BET_SETTLE_SECTION,
    "betandsettle": BET_SETTLE_SECTION,
    "idempotency": BET_SETTLE_SECTION,
    "rollback": CANCEL_BET_SECTION,
    "rollback_bet": CANCEL_BET_SECTION,
    "rollback_settled_bet": CANCEL_BET_SECTION,
    "rollback_by_round_or_rollback_by_bet": CANCEL_BET_SECTION,
    "rollback_bet_and_settle": CANCEL_BET_SECTION,
    "rollback_betandsettle": CANCEL_BET_SECTION,
    "freespin": BET_SETTLE_SECTION,
    "jackpot": BET_SETTLE_SECTION,
    "slots": BET_SETTLE_SECTION,
    "slot_game": BET_SETTLE_SECTION,
    "arcade_game": BET_SETTLE_SECTION,
    "live_game": BET_SETTLE_SECTION,
    "mini_game": BET_SETTLE_SECTION,
    "instant_win": BET_SETTLE_SECTION,
    "poker_game": BET_SETTLE_SECTION,
    "table_game": BET_SETTLE_SECTION,
    "video_bingo": BET_SETTLE_SECTION,
    "crash_game": BET_SETTLE_SECTION,
}

GENERATED_XMIND_STRUCTURE = {
    "API parameter test": {
        "description": "Parameter validation cases are grouped by endpoint, then by parameter.",
        "children": ["<endpoint>", "<parameter>"],
    },
    "User Behavior": {
        "description": "Business-flow cases use canonical source-path mapping.",
        "children": {
            "Launch Game": "Launch URL and authenticate-related cases.",
            "Get Player balance": "Balance endpoint cases.",
            "Bet and Settle": {
                "children": {
                    "Game type": {
                        "children": {
                            "Game category": list(GAME_CATEGORY_MODULES.values()),
                            "Main flow": [],
                        }
                    },
                    "Bet config": [],
                    "Settle config": [],
                    "BetAndSettle config": [],
                    "Special accounts": [],
                    "Player / Game status": [],
                }
            },
            "Cancel Bet": {
                "children": {
                    "Main flow": [],
                    "Cancel config": [],
                    "Special accounts": [],
                    "Player / Game status": [],
                }
            },
        },
    },
}


@dataclass(frozen=True)
class UserBehaviorMappingDecision:
    output_section: str | None
    category: str
    rule_id: str
    status: str
    reason: str


def normalize_source_segment(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def normalize_source_path(value: Any) -> tuple[str, ...]:
    return tuple(
        normalize_source_segment(part)
        for part in str(value or "").split(">")
        if str(part).strip()
    )


def path_contains_segments(path: Any, fragment: Any) -> bool:
    path_parts = normalize_source_path(path)
    fragment_parts = normalize_source_path(fragment)
    if not fragment_parts or len(fragment_parts) > len(path_parts):
        return False
    width = len(fragment_parts)
    return any(path_parts[index : index + width] == fragment_parts for index in range(len(path_parts) - width + 1))


def map_user_behavior_case(
    selected_category: str,
    reference_case: dict[str, Any],
) -> UserBehaviorMappingDecision:
    category = str(selected_category or "").strip()
    module = normalize_source_segment(reference_case.get("module"))
    parts = normalize_source_path(reference_case.get("path"))
    leaf = parts[-1] if parts else ""

    if "special test cases" in parts:
        return _decision(None, category, "excluded.special_test_cases", "excluded", "Source-only Special test cases branch is not mapped to Special accounts.")

    if category == "launch_game" or module == "launch game":
        return _mapped(LAUNCH_GAME_SECTION, category, "direct.launch_game", "Launch Game source module.")
    if category == "balance" or module in {"balance", "get player balance"}:
        return _mapped(BALANCE_SECTION, category, "direct.balance", "Balance source module.")
    if category == "authenticate" or module == "authenticate":
        return _mapped(LAUNCH_GAME_SECTION, category, "direct.authenticate", "Authenticate generation contract.")

    game_category = GAME_CATEGORY_MODULES.get(module)
    if game_category and parts[:1] == ("game category",):
        return _mapped(
            f"{BET_SETTLE_GAME_CATEGORY} > {game_category}",
            category,
            "game_category.module",
            f"Canonical game category module {game_category}.",
        )

    cancel_scope = _is_cancel_scope(category, module, parts)
    if leaf == "special accounts":
        return _mapped(CANCEL_SPECIAL_ACCOUNTS if cancel_scope else BET_SETTLE_SPECIAL_ACCOUNTS, category, "cancel.special_accounts" if cancel_scope else "bet.special_accounts", "Explicit Special accounts source leaf.")
    if leaf == "player / game status":
        return _mapped(CANCEL_STATUS if cancel_scope else BET_SETTLE_STATUS, category, "cancel.player_game_status" if cancel_scope else "bet.player_game_status", "Explicit Player / Game status source leaf.")
    if leaf == "main flow":
        return _mapped(CANCEL_MAIN_FLOW if cancel_scope else BET_SETTLE_MAIN_FLOW, category, "cancel.main_flow" if cancel_scope else "bet.main_flow", "Explicit main flow source leaf.")
    if leaf == "cancel config":
        return _mapped(CANCEL_CONFIG_SECTION, category, "cancel.cancel_config", "Explicit cancel config source leaf.")
    if leaf == "bet config":
        return _mapped(BET_CONFIG_SECTION, category, "bet.bet_config", "Explicit bet config source leaf.")
    if leaf == "settle config":
        return _mapped(SETTLE_CONFIG_SECTION, category, "bet.settle_config", "Explicit settle config source leaf.")
    if leaf == "betandsettle config":
        return _mapped(BET_AND_SETTLE_CONFIG_SECTION, category, "bet.bet_and_settle_config", "Explicit combined-controller config source leaf.")
    if leaf == "adjustment config":
        return _mapped(CANCEL_CONFIG_SECTION if cancel_scope else SETTLE_CONFIG_SECTION, category, "cancel.cancel_config" if cancel_scope else "bet.settle_config", "Adjustment config follows its controller scope.")

    if category == "authentication_is_necessary" or path_contains_segments(
        reference_case.get("path"), "Authenticate > Authentication is necessary"
    ):
        return _mapped(BET_CONFIG_SECTION, category, "bet.authentication_required", "Bet without required authentication is a Bet config error case.")

    title_rule = _legacy_title_rule(reference_case, cancel_scope, category)
    if title_rule is not None:
        return title_rule

    if category in {"freespin", "jackpot"}:
        return _mapped(BET_SETTLE_MAIN_FLOW, category, "fallback.freespin_jackpot_main_flow", "Capability flow without an explicit legacy leaf.")
    if category in {"modify_settlement_adjustment", "cancel_settlement_adjustment"}:
        output = CANCEL_CONFIG_SECTION if cancel_scope else SETTLE_CONFIG_SECTION
        return _mapped(output, category, "fallback.adjustment_config", "Adjustment fallback follows controller scope.")
    if cancel_scope or category in {"rollback", "rollback_bet", "rollback_settled_bet"}:
        return _mapped(CANCEL_CONFIG_SECTION, category, "fallback.rollback_config", "Rollback fallback maps to Cancel config.")

    return _decision(None, category, "unmapped.no_rule", "unmapped", f"No canonical mapping rule for module={module!r}, path={parts!r}.")


def canonicalize_output_section_alias(output_section: str) -> str:
    if output_section == DEBIT_CREDIT_SECTION or output_section.startswith(f"{DEBIT_CREDIT_SECTION} > "):
        return BET_SETTLE_SECTION + output_section[len(DEBIT_CREDIT_SECTION) :]
    if output_section == CANCEL_DEBIT_SECTION or output_section.startswith(f"{CANCEL_DEBIT_SECTION} > "):
        return CANCEL_BET_SECTION + output_section[len(CANCEL_DEBIT_SECTION) :]
    return output_section


def is_allowed_user_behavior_output_section(output_section: str) -> bool:
    canonical = canonicalize_output_section_alias(str(output_section or ""))
    return canonical in CANONICAL_USER_BEHAVIOR_LEAF_SECTIONS


def build_user_behavior_mapping_report(xmind_detail_root: Path | str) -> dict[str, Any]:
    root = Path(xmind_detail_root) / "User_Behavior_map"
    modules_dir = root / "modules"
    decisions: list[dict[str, Any]] = []
    if modules_dir.exists():
        for module_path in sorted(modules_dir.glob("*.json")):
            try:
                payload = json.loads(module_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for case in payload.get("cases", []):
                if not isinstance(case, dict):
                    continue
                decision = map_user_behavior_case("inventory", case)
                item = asdict(decision)
                item.update(
                    {
                        "source_case_id": str(case.get("id", "")),
                        "source_module": str(case.get("module", "")),
                        "source_path": str(case.get("path", "")),
                    }
                )
                decisions.append(item)

    status_counts = Counter(item["status"] for item in decisions)
    rule_counts = Counter(item["rule_id"] for item in decisions)
    source_meta = _read_source_meta(root)
    return {
        "contract_version": MAPPING_CONTRACT_VERSION,
        "source_directory": str(root),
        "source_xmind_sha256": source_meta.get("sha256", ""),
        "total_cases": len(decisions),
        "mapped": status_counts.get("mapped", 0),
        "excluded": status_counts.get("excluded", 0),
        "unmapped": status_counts.get("unmapped", 0),
        "accounted": sum(status_counts.values()),
        "rule_counts": dict(sorted(rule_counts.items())),
        "exceptions": [item for item in decisions if item["status"] != "mapped"],
    }


def _read_source_meta(root: Path) -> dict[str, Any]:
    path = root / "source_meta" / "User_Behavior_map_source_meta.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _is_cancel_scope(category: str, module: str, parts: tuple[str, ...]) -> bool:
    return (
        module in {"cancel bet", "rollback"}
        or category.startswith("rollback")
        or category == "cancel_settlement_adjustment"
        or (len(parts) >= 2 and parts[0] == "mandatory" and parts[1] == "cancel bet")
    )


def _legacy_title_rule(
    reference_case: dict[str, Any], cancel_scope: bool, category: str
) -> UserBehaviorMappingDecision | None:
    title = str(
        reference_case.get("scenario")
        or reference_case.get("title")
        or reference_case.get("child_topic")
        or ""
    )
    normalized = " ".join(title.casefold().split())
    if any(phrase in normalized for phrase in SPECIAL_ACCOUNT_TITLE_PHRASES):
        return _mapped(CANCEL_SPECIAL_ACCOUNTS if cancel_scope else BET_SETTLE_SPECIAL_ACCOUNTS, category, "legacy.title_special_accounts", "Legacy title fallback for a source path without a canonical leaf.")
    if any(phrase in normalized for phrase in PLAYER_GAME_STATUS_TITLE_PHRASES):
        return _mapped(CANCEL_STATUS if cancel_scope else BET_SETTLE_STATUS, category, "legacy.title_player_game_status", "Legacy title fallback for a source path without a canonical leaf.")
    return None


def _mapped(output_section: str, category: str, rule_id: str, reason: str) -> UserBehaviorMappingDecision:
    return _decision(output_section, category, rule_id, "mapped", reason)


def _decision(
    output_section: str | None,
    category: str,
    rule_id: str,
    status: str,
    reason: str,
) -> UserBehaviorMappingDecision:
    return UserBehaviorMappingDecision(output_section, category, rule_id, status, reason)
