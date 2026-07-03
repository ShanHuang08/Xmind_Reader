"""Infer endpoint topology and parameter semantics for User Behavior templates."""

from __future__ import annotations

from typing import Any


BET_ROLES = {"bet"}
SETTLEMENT_ROLES = {"settlement", "combined_bet_settlement"}
COMBINED_BET_SETTLEMENT_ROLES = {"combined_bet_settlement"}
AUTHENTICATION_ROLES = {"authentication"}

AUTHENTICATION_REQUIRED_TERMS = {
    "authentication required",
    "authentication is required",
    "authentication is necessary",
    "authentication is mandatory",
    "authenticate required",
    "authenticate is required",
    "authenticate first",
    "must authenticate",
    "must call authenticate",
    "call authenticate before",
    "not authenticated",
    "unauthenticated",
    "unauthorized",
    "invalid token",
    "missing token",
    "token required",
    "token is required",
    "invalid session",
    "missing session",
    "session required",
    "session is required",
}

ACTION_CONTROL_NAMES = {
    "action",
    "method",
    "operation",
    "command",
    "type",
    "requesttype",
    "transactiontype",
}

ROUND_END_CONTROL_NAMES = {
    "roundcompleted",
    "isendround",
    "roundend",
    "endround",
    "isroundend",
    "isfinished",
    "finished",
    "completed",
    "iscomplete",
    "complete",
}

STATUS_NAMES = {
    "status",
    "playstatus",
    "gamestatus",
    "roundstatus",
    "betstatus",
    "settlementstatus",
}

ROUND_ID_NAMES = {
    "roundid",
    "round_id",
    "gameid",
    "playid",
    "handid",
}

IDEMPOTENCY_NAMES = {
    "transactionid",
    "transaction_id",
    "txid",
    "referenceid",
    "reference_id",
    "requestid",
    "request_id",
    "orderid",
    "ordercode",
    "betid",
    "roundid",
}

JACKPOT_CONTROL_NAMES = {
    "jackpot",
    "jackpotamount",
    "jackpotaward",
    "jackpotcontribution",
    "jackpotwin",
    "jackpotpayout",
    "jackpotprize",
    "jackpotid",
    "mjpwin",
    "mjpcomm",
    "jpwin",
    "jpamount",
}

FREESPIN_CONTROL_NAMES = {
    "freespin",
    "freespins",
    "freegame",
    "freegames",
    "freebet",
    "freebets",
    "bonusid",
    "bonuscode",
    "campaignid",
    "campaigncode",
    "promotionid",
    "promoid",
    "featureid",
    "featurecode",
}


def analyze_endpoint_topology(
    endpoint_roles: list[dict[str, Any]], error_codes: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Analyze endpoint roles/parameters before selecting User Behavior templates."""
    bet_endpoints = _endpoints_by_role(endpoint_roles, BET_ROLES)
    settlement_endpoints = _endpoints_by_role(endpoint_roles, SETTLEMENT_ROLES)
    combined_bet_settlement_endpoints = _endpoints_by_role(
        endpoint_roles, COMBINED_BET_SETTLEMENT_ROLES
    )
    authentication_endpoints = _endpoints_by_role(endpoint_roles, AUTHENTICATION_ROLES)
    authentication_required_evidence = _authentication_required_evidence(
        endpoint_roles, error_codes or []
    )
    all_parameters = [
        parameter
        for endpoint in endpoint_roles
        for parameter in endpoint.get("request_parameters", [])
        if isinstance(parameter, dict)
    ]

    bet_action_parameters = _matching_parameter_names(bet_endpoints, ACTION_CONTROL_NAMES)
    settlement_round_end_parameters = _matching_parameter_names(
        settlement_endpoints, ROUND_END_CONTROL_NAMES
    )
    settlement_status_parameters = _matching_parameter_names(settlement_endpoints, STATUS_NAMES)
    settlement_jackpot_parameters = _matching_parameter_names(
        settlement_endpoints, JACKPOT_CONTROL_NAMES
    )
    bet_free_spin_parameters = _matching_parameter_names_or_text(
        bet_endpoints, FREESPIN_CONTROL_NAMES
    )
    settlement_free_spin_parameters = _matching_parameter_names_or_text(
        settlement_endpoints, FREESPIN_CONTROL_NAMES
    )
    free_spin_parameters = sorted(
        set(bet_free_spin_parameters + settlement_free_spin_parameters)
    )

    return {
        "endpoint_topology": {
            "authenticate": {
                "mode": "endpoint_present"
                if authentication_endpoints
                else "missing_authenticate_endpoint",
                "endpoint_count": len(authentication_endpoints),
                "endpoints": [
                    endpoint.get("endpoint", "") for endpoint in authentication_endpoints
                ],
                "authentication_required": bool(
                    authentication_endpoints and authentication_required_evidence
                ),
                "required_evidence": authentication_required_evidence,
            },
            "bet": {
                "mode": _bet_topology_mode(bet_endpoints, bet_action_parameters),
                "endpoint_count": len(bet_endpoints),
                "endpoints": [endpoint.get("endpoint", "") for endpoint in bet_endpoints],
                "action_parameters": bet_action_parameters,
                "free_spin_parameters": bet_free_spin_parameters,
            },
            "settlement": {
                "mode": "has_round_end_control_parameter"
                if settlement_round_end_parameters
                else "no_round_end_control_parameter",
                "endpoint_count": len(settlement_endpoints),
                "endpoints": [endpoint.get("endpoint", "") for endpoint in settlement_endpoints],
                "round_end_control_parameters": settlement_round_end_parameters,
                "status_parameters": settlement_status_parameters,
                "jackpot_parameters": settlement_jackpot_parameters,
                "free_spin_parameters": settlement_free_spin_parameters,
            },
            "bet_and_settle": {
                "mode": "combined_endpoint"
                if combined_bet_settlement_endpoints
                else "missing_combined_endpoint",
                "endpoint_count": len(combined_bet_settlement_endpoints),
                "endpoints": [
                    endpoint.get("endpoint", "")
                    for endpoint in combined_bet_settlement_endpoints
                ],
            },
        },
        "parameter_semantics": {
            "action_control": bool(_matching_names(all_parameters, ACTION_CONTROL_NAMES)),
            "round_end_control": bool(settlement_round_end_parameters),
            "settlement_status": bool(settlement_status_parameters),
            "round_identifier": bool(_matching_names(all_parameters, ROUND_ID_NAMES)),
            "idempotency_key": bool(_matching_names(all_parameters, IDEMPOTENCY_NAMES)),
            "combined_bet_settlement": bool(combined_bet_settlement_endpoints),
            "authentication": bool(authentication_endpoints),
            "authentication_required": bool(
                authentication_endpoints and authentication_required_evidence
            ),
            "jackpot_control": bool(settlement_jackpot_parameters),
            "free_spin_control": bool(free_spin_parameters),
        },
    }


def _authentication_required_evidence(
    endpoint_roles: list[dict[str, Any]], error_codes: list[dict[str, Any]]
) -> list[str]:
    evidence = []
    for item in error_codes:
        text = _searchable_text(item)
        if _mentions_authentication_requirement(text):
            evidence.append(_compact_evidence("error_code", item))

    for endpoint in endpoint_roles:
        text = _searchable_text(endpoint)
        if _mentions_authentication_requirement(text):
            evidence.append(_compact_evidence("endpoint", endpoint))

    return sorted(set(item for item in evidence if item))


def _mentions_authentication_requirement(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in AUTHENTICATION_REQUIRED_TERMS)


def _searchable_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_searchable_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_searchable_text(item) for item in value)
    return str(value)


def _compact_evidence(source: str, item: dict[str, Any]) -> str:
    if source == "error_code":
        code = str(item.get("code", "")).strip()
        context = str(
            item.get("context") or item.get("message") or item.get("description") or ""
        ).strip()
        return f"error_code:{code}:{context[:160]}".strip(":")
    endpoint = str(item.get("endpoint", "")).strip()
    section = str(item.get("section", "")).strip()
    return f"endpoint:{endpoint}:{section[:120]}".strip(":")


def _endpoints_by_role(
    endpoint_roles: list[dict[str, Any]], roles: set[str]
) -> list[dict[str, Any]]:
    return [
        endpoint
        for endpoint in endpoint_roles
        if isinstance(endpoint, dict) and str(endpoint.get("role", "")) in roles
    ]


def _bet_topology_mode(
    bet_endpoints: list[dict[str, Any]], action_parameters: list[str]
) -> str:
    if len(bet_endpoints) >= 2:
        return "two_bet_endpoint"
    if len(bet_endpoints) == 1:
        return "one_bet_endpoint_with_action_parameter" if action_parameters else "one_bet_endpoint"
    return "missing_bet_endpoint"


def _matching_parameter_names(
    endpoints: list[dict[str, Any]], normalized_names: set[str]
) -> list[str]:
    parameters = [
        parameter
        for endpoint in endpoints
        for parameter in endpoint.get("request_parameters", [])
        if isinstance(parameter, dict)
    ]
    return _matching_names(parameters, normalized_names)


def _matching_parameter_names_or_text(
    endpoints: list[dict[str, Any]], normalized_names: set[str]
) -> list[str]:
    parameters = [
        parameter
        for endpoint in endpoints
        for parameter in endpoint.get("request_parameters", [])
        if isinstance(parameter, dict)
    ]
    matches = []
    for parameter in parameters:
        name = str(parameter.get("name", "")).strip()
        if not name:
            continue
        searchable = _normalize_name(_searchable_text(parameter))
        if any(term in searchable for term in normalized_names):
            matches.append(name)
    return sorted(set(matches))


def _matching_names(parameters: list[dict[str, Any]], normalized_names: set[str]) -> list[str]:
    matches = []
    for parameter in parameters:
        name = str(parameter.get("name", "")).strip()
        if not name:
            continue
        normalized = _normalize_name(name)
        if normalized in normalized_names:
            matches.append(name)
    return sorted(set(matches))


def _normalize_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())
