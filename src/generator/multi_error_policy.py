"""Selection hook for vendors with multiple parameter-validation errors.

The normal generator path selects one documented parameter error.  Some vendors
document more than one error code for parameter validation, so a later step can
select the code from the mutation being tested (for example, wrong type versus
invalid syntax).  This module is the single dispatch point for that logic.

Vendor-specific rules intentionally do not live in the main generator.  Until a
rule is registered here, ``resolve`` returns ``None`` and the caller preserves
the existing fallback/error behavior.
"""

from __future__ import annotations

from typing import Any


HUB88_PARAMETER_ERRORS = frozenset(
    {
        "RS_ERROR_WRONG_SYNTAX",
        "RS_ERROR_WRONG_TYPES",
    }
)
HUB88_INVALID_TOKEN = "RS_ERROR_INVALID_TOKEN"
HUB88_TOKEN_EXPIRED = "RS_ERROR_TOKEN_EXPIRED"


def resolve(
    *,
    vendor: str,
    candidate_errors: list[dict[str, Any]],
    mutation_kind: str = "",
    parameter: dict[str, Any] | None = None,
    endpoint: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the selected error, or ``None`` when no policy matches.

    ``mutation_kind`` is deliberately structured rather than a step-title
    string.  Planned values include ``missing``, ``blank``, ``wrong_type``,
    ``invalid_format``, ``negative``, ``zero``, and ``decimal_precision``.
    The Hub88 and other vendor rules will be added here later.
    """
    if len(candidate_errors) < 2:
        return None

    vendor_key = "".join(char for char in str(vendor).lower() if char.isalnum())
    codes = candidate_codes(candidate_errors)
    if vendor_key == "hub88" and HUB88_INVALID_TOKEN in codes and _is_token_parameter(parameter):
        # A syntactically valid but fake/unknown token is an invalid-token
        # case.  Token expiry is a behavior/session condition and must never
        # be selected by API parameter mutation steps.
        if mutation_kind == "space":
            return _error_by_code(candidate_errors, HUB88_INVALID_TOKEN)

    if vendor_key == "hub88" and HUB88_PARAMETER_ERRORS.issubset(codes):
        syntax_code = _error_by_code(candidate_errors, "RS_ERROR_WRONG_SYNTAX")
        types_code = _error_by_code(candidate_errors, "RS_ERROR_WRONG_TYPES")
        if mutation_kind in {"wrong_type", "wrong_data_type"}:
            return types_code
        if mutation_kind == "space" and _space_is_wrong_type(parameter):
            return types_code
        # Missing, blank, malformed, and value/precision violations are
        # request-form violations for the Hub88 rule set.
        return syntax_code

    return None


def resolve_behavior(
    *,
    vendor: str,
    error_codes: list[dict[str, Any]],
    category: str = "",
    scenario: str = "",
) -> dict[str, Any] | None:
    """Select token-expiry errors for documented Hub88 behavior cases.

    The behavior map represents a known token whose session was terminated.
    This is intentionally separate from parameter mutation selection: an
    expired token is not a malformed API parameter.  Win/rollback behavior is
    excluded because Hub88 explicitly says expiry must not be checked there.
    """
    vendor_key = "".join(char for char in str(vendor).lower() if char.isalnum())
    if vendor_key != "hub88":
        return None

    normalized = " ".join(str(scenario).casefold().split())
    category_key = " ".join(str(category).casefold().split())
    is_balance_after_termination = (
        "terminate the token" in normalized
        and "get player balance" in normalized
        and category_key == "balance"
    )
    is_bet_after_termination = (
        "terminate the game" in normalized
        and "bet again" in normalized
        and category_key == "bet"
    )
    if not (is_balance_after_termination or is_bet_after_termination):
        return None
    return _error_by_code(error_codes, HUB88_TOKEN_EXPIRED)


def candidate_codes(candidate_errors: list[dict[str, Any]]) -> set[str]:
    """Return normalized codes for policy dispatch and test assertions."""
    return {
        str(item.get("code", "")).strip()
        for item in candidate_errors
        if str(item.get("code", "")).strip()
    }


def _error_by_code(candidate_errors: list[dict[str, Any]], code: str) -> dict[str, Any]:
    for item in candidate_errors:
        if str(item.get("code", "")).strip() == code:
            return {
                "code": code,
                "source": "documented",
                "description": str(item.get("context") or item.get("description") or ""),
                "selection": "multi_error_policy",
            }
    # This branch is unreachable when policy dispatch is guarded by the exact
    # candidate code set. Keep it fail-closed instead of inventing an error.
    return {}


def _space_is_wrong_type(parameter: dict[str, Any] | None) -> bool:
    if not parameter:
        return False
    param_type = str(parameter.get("type", "")).lower()
    return not ("string" in param_type or "uuid" in param_type)


def _is_token_parameter(parameter: dict[str, Any] | None) -> bool:
    if not parameter:
        return False
    name = str(parameter.get("name", "")).strip().casefold()
    return name.split(".")[-1].replace("-", "_") == "token"
