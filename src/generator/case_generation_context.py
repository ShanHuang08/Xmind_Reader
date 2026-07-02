"""Build normalized context for test case generation."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


def load_draft(path: Path | str) -> dict[str, Any]:
    draft_path = Path(path)
    with draft_path.open(encoding="utf-8") as file:
        return json.load(file)


def save_draft(draft: dict[str, Any], path: Path | str) -> Path:
    draft_path = Path(path)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft_path


def build_generation_context(draft: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of draft data needed by deterministic generators."""
    return {
        "vendor": draft.get("vendor", ""),
        "capability_profile": draft.get("capability_profile", {}),
        "endpoint_roles": draft.get("endpoint_roles", []),
        "endpoint_analysis": draft.get("endpoint_analysis", {}),
        "error_codes": draft.get("error_codes", []),
        "generation_mapping": draft.get("generation_mapping", {}),
        "case_authoring_rules": draft.get("case_authoring_rules", {}),
        "default_test_account": _default_test_account(draft),
        "parameter_error": _select_parameter_error(draft.get("error_codes", [])),
    }


def _default_test_account(draft: dict[str, Any]) -> str:
    rules = draft.get("case_authoring_rules", {})
    return rules.get("default_test_account") or _account_from_vendor(draft.get("vendor", ""))


def _account_from_vendor(vendor: str, today: date | None = None) -> str:
    current = today or date.today()
    letters = "".join(re.findall(r"[A-Za-z]", vendor or "")).lower()
    prefix = (letters[:3] or "ven").ljust(3, "x")
    return f"{prefix}{current:%y%m%d}"


def _select_parameter_error(error_codes: list[dict[str, Any]]) -> dict[str, str]:
    for item in error_codes:
        text = " ".join(str(item.get(key, "")) for key in ("code", "context", "message", "description"))
        lowered = text.lower()
        if "bad parameter" in lowered or "bad parameters" in lowered or "invalid request" in lowered:
            return {
                "code": str(item.get("code", "")).strip(),
                "source": "documented",
                "description": str(item.get("context") or item.get("message") or item.get("description") or ""),
            }

    for item in error_codes:
        code = str(item.get("code", "")).strip()
        if code and code not in {"0", "ok", "OK", "success", "SUCCESS"}:
            return {
                "code": code,
                "source": "inferred_from_limited_vendor_codes",
                "description": str(item.get("context") or item.get("message") or item.get("description") or ""),
            }

    return {
        "code": "UNKNOWN_PARAMETER_ERROR",
        "source": "inferred_from_limited_vendor_codes",
        "description": "No documented parameter error code was found.",
    }
