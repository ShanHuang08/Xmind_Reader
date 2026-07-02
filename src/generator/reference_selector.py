"""Select reference knowledge chunks for generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


MANDATORY_CATEGORIES = {
    "launch_game",
    "balance",
    "bet",
    "settlement",
    "rollback",
    "amount_precision",
}

CONDITIONAL_MANDATORY_CATEGORY_RULES = {
    "authenticate": {
        "category": "authenticate",
        "conditions": [
            {
                "path": ("endpoint_topology", "authenticate", "mode"),
                "required_value": "endpoint_present",
            }
        ],
    },
    "bet_and_settle": {
        "category": "bet_and_settle",
        "conditions": [
            {
                "path": ("endpoint_topology", "bet_and_settle", "mode"),
                "required_value": "combined_endpoint",
            }
        ],
    },
    "bet_and_settle_has_round_end_control_parameter": {
        "category": "bet_and_settle_has_round_end_control_parameter",
        "conditions": [
            {
                "path": ("endpoint_topology", "bet_and_settle", "mode"),
                "required_value": "combined_endpoint",
            },
            {
                "path": ("parameter_semantics", "round_end_control"),
                "required_value": True,
            },
        ],
    },
    "bet_and_settle_no_round_end_control_parameter": {
        "category": "bet_and_settle_no_round_end_control_parameter",
        "conditions": [
            {
                "path": ("endpoint_topology", "bet_and_settle", "mode"),
                "required_value": "combined_endpoint",
            },
            {
                "path": ("parameter_semantics", "round_end_control"),
                "required_value": False,
            },
        ],
    },
}

CAPABILITY_CATEGORY_RULES = {
    "multiple_bets": "multiple_bets",
    "multiple_settlements": [
        "multiple_settlements",
        "multiple_settlements_has_round_end_control_parameter",
        "multiple_settlements_no_round_end_control_parameter",
    ],
    "rollback_settlements": "rollback_settled_bet",
    "modify_settlements_adjustment": "modify_settlement_adjustment",
    "cancel_bet": "rollback_bet",
    "free_spin": "freespin",
    "idempotency": "idempotency",
}


def selected_categories(
    capability_profile: dict[str, Any], endpoint_analysis: dict[str, Any] | None = None
) -> list[str]:
    """Choose reusable knowledge categories from vendor capabilities."""
    supports = capability_profile.get("supports", {})
    categories = set(MANDATORY_CATEGORIES)
    analysis = endpoint_analysis or {}
    for rule in CONDITIONAL_MANDATORY_CATEGORY_RULES.values():
        if _conditions_match(analysis, rule["conditions"]):
            categories.add(rule["category"])
    for capability, category_or_categories in CAPABILITY_CATEGORY_RULES.items():
        if supports.get(capability):
            if isinstance(category_or_categories, str):
                categories.add(category_or_categories)
            else:
                categories.update(category_or_categories)
    if supports.get("multiple_bets"):
        bet_mode = _nested_value(analysis, ("endpoint_topology", "bet", "mode"))
        if bet_mode in {"one_bet_endpoint", "one_bet_endpoint_with_action_parameter"}:
            categories.add("multiple_bets_one_bet_endpoint")
        elif bet_mode == "two_bet_endpoint":
            categories.add("multiple_bets_two_bet_endpoint")
    if supports.get("jackpot") and _nested_value(
        analysis, ("parameter_semantics", "jackpot_control")
    ):
        categories.add("jackpot")
    return sorted(categories)


def _conditions_match(data: dict[str, Any], conditions: list[dict[str, Any]]) -> bool:
    return all(
        _nested_value(data, condition["path"]) == condition["required_value"]
        for condition in conditions
    )


def _nested_value(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def select_reference_files(xmind_detail_root: Path | str, categories: list[str]) -> list[Path]:
    """Return likely reference chunk files for the selected categories.

    This is intentionally conservative: it finds existing tag/module/markdown files
    whose stem contains one of the selected category names. Missing files are fine;
    deterministic generation can still run from the draft contract.
    """
    root = Path(xmind_detail_root)
    if not root.exists():
        return []

    category_terms = {category.lower() for category in categories}
    matches: list[Path] = []
    for folder_name in ("tags", "modules", "markdown"):
        for path in root.glob(f"*/{folder_name}/**/*"):
            if not path.is_file():
                continue
            path_keys = _path_category_keys(path, root)
            if category_terms.intersection(path_keys):
                matches.append(path)
    return sorted(matches)


def _path_category_keys(path: Path, root: Path) -> set[str]:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path

    parts = [_normalize_part(part) for part in relative.parts]
    marker_index = _first_marker_index(parts)
    category_parts = parts[marker_index + 1 :] if marker_index is not None else parts
    if not category_parts:
        return set()

    category_parts[-1] = Path(category_parts[-1]).stem.lower().replace("-", "_")
    keys = set(category_parts)
    for start in range(len(category_parts)):
        keys.add("_".join(category_parts[start:]))
    return keys


def _first_marker_index(parts: list[str]) -> int | None:
    for marker in ("tags", "modules", "markdown"):
        if marker in parts:
            return parts.index(marker)
    return None


def _normalize_part(part: str) -> str:
    return Path(part).stem.lower().replace("-", "_")
