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

CAPABILITY_CATEGORY_RULES = {
    "multiple_bets": "multiple_bets",
    "multiple_settlements": "multiple_settlements",
    "rollback_settlements": "rollback_settled_bet",
    "modify_settlements_adjustment": "modify_settlement_adjustment",
    "cancel_bet": "rollback_bet",
    "free_spin": "freespin",
    "jackpot": "jackpot",
    "idempotency": "idempotency",
}


def selected_categories(capability_profile: dict[str, Any]) -> list[str]:
    """Choose reusable knowledge categories from vendor capabilities."""
    supports = capability_profile.get("supports", {})
    categories = set(MANDATORY_CATEGORIES)
    for capability, category in CAPABILITY_CATEGORY_RULES.items():
        if supports.get(capability):
            categories.add(category)
    return sorted(categories)


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
        for path in root.glob(f"*/{folder_name}/*"):
            if not path.is_file():
                continue
            stem = path.stem.lower()
            if any(term in stem for term in category_terms):
                matches.append(path)
    return sorted(matches)
