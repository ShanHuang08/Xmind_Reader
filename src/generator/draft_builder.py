"""Build a Codex-facing draft JSON scaffold for new vendor test case generation."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


FALLBACK_GAME_CODES = {
    "Esoterica": "ESOTERICA_burningSlot5",
}


ENDPOINT_ROLE_RULES = {
    "authenticate": "authentication",
    "balance": "balance_check",
    "betandresult": "combined_bet_settlement",
    "bet": "bet",
    "result": "settlement",
    "refund": "cancel_bet",
    "rollback": "rollback",
    "endround": "balance_confirmation_only",
}


KNOWLEDGE_CATEGORY_TO_XMIND_SECTION = {
    "parameter_validation": "API parameter test",
    "launch_game": "User Behavior > Launch Game",
    "authenticate": "User Behavior > Launch Game",
    "balance": "User Behavior > Get Player balance",
    "bet": "User Behavior > Bet and Settle",
    "settlement": "User Behavior > Bet and Settle",
    "amount_precision": "User Behavior > Bet and Settle",
    "multiple_bets": "User Behavior > Bet and Settle",
    "multiple_settlements": "User Behavior > Bet and Settle",
    "modify_settlement_adjustment": "User Behavior > Bet and Settle",
    "settle_by_round_or_settle_by_bet": "User Behavior > Bet and Settle",
    "bet_and_settle": "User Behavior > Bet and Settle",
    "betandsettle": "User Behavior > Bet and Settle",
    "idempotency": "User Behavior > Bet and Settle",
    "rollback": "User Behavior > Cancel Bet",
    "rollback_bet": "User Behavior > Cancel Bet",
    "rollback_settled_bet": "User Behavior > Cancel Bet",
    "rollback_by_round_or_rollback_by_bet": "User Behavior > Cancel Bet",
    "rollback_bet_and_settle": "User Behavior > Cancel Bet",
    "rollback_betandsettle": "User Behavior > Cancel Bet",
    "freespin": "User Behavior > Bet and Settle",
    "jackpot": "User Behavior > Bet and Settle",
    "slots": "User Behavior > Game type > Slots",
    "arcade_game": "User Behavior > Game type > Arcade game",
    "mini_game": "User Behavior > Game type > Mini game",
    "crash_game": "User Behavior > Game type > Crash game",
}


GENERATED_XMIND_STRUCTURE = {
    "API parameter test": {
        "description": "Parameter validation cases are grouped by endpoint, then by parameter.",
        "children": ["<endpoint>", "<parameter>"],
    },
    "User Behavior": {
        "description": "Business-flow cases are grouped by QA-facing behavior section.",
        "children": {
            "Launch Game": "Launch URL and authenticate-related cases.",
            "Get Player balance": "Balance endpoint cases.",
            "Bet and Settle": "Bet, settlement, betAndSettle, amount precision, multiple bets, multiple settlements, freespin settlement, jackpot settlement, and idempotency cases.",
            "Cancel Bet": "Rollback, cancel bet, rollback settled bet, and rollback betAndSettle cases.",
            "Game type": "Game front-end cases grouped by game type, such as Slots, Arcade game, Mini game, and Crash game.",
        },
    },
}


def build_draft(vendor: str, vendor_detail_root: Path, output_root: Path) -> Path:
    vendor_dir = Path(vendor_detail_root) / vendor
    if not vendor_dir.exists():
        raise FileNotFoundError(f"Vendor detail folder does not exist: {vendor_dir}")

    capability_profile = _read_json(vendor_dir / "capability_profile.json")
    endpoints = _read_json(vendor_dir / "endpoints.json")
    error_codes = _read_json(vendor_dir / "error_codes.json")
    checklist_path = vendor_dir / "vendor_master_checklist.json"
    checklist = _read_json(checklist_path) if checklist_path.exists() else []
    game_codes_path = vendor_dir / "game_codes.json"
    game_codes = _read_json(game_codes_path) if game_codes_path.exists() else _extract_game_codes_from_raw(vendor_dir)

    draft = {
        "schema_version": "draft-test-cases/v1",
        "status": "draft_context_only",
        "vendor": vendor,
        "purpose": (
            "This file is a Codex working draft. It prepares source context and rules "
            "for future new-vendor test case generation. It does not contain generated "
            "test cases yet."
        ),
        "source_files": {
            "vendor_detail": str(vendor_dir),
            "capability_profile": str(vendor_dir / "capability_profile.json"),
            "endpoints": str(vendor_dir / "endpoints.json"),
            "error_codes": str(vendor_dir / "error_codes.json"),
        },
        "capability_profile": capability_profile,
        "vendor_master_checklist": checklist,
        "game_codes": game_codes,
        "endpoint_roles": [_endpoint_role(endpoint) for endpoint in endpoints],
        "error_codes": error_codes,
        "supplementary_sources": _supplementary_sources(vendor_dir),
        "case_authoring_rules": _case_authoring_rules(vendor, endpoints, game_codes),
        "generation_mapping": _generation_mapping(),
        "pending_user_questions": _pending_user_questions(vendor, game_codes),
        "test_cases": [],
    }

    output_dir = Path(output_root) / vendor
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "draft_test_cases.json"
    output_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _endpoint_role(endpoint: dict[str, Any]) -> dict[str, Any]:
    path = endpoint.get("endpoint", "")
    role = _infer_role(path)
    generation_note = ""
    if role == "balance_confirmation_only":
        generation_note = (
            "Do not use this endpoint to close rounds in API integration test cases. "
            "Round closing is handled by settlement/result flow. Use this endpoint only "
            "when a scenario needs a balance confirmation call."
        )
    return {
        "endpoint": path,
        "role": role,
        "generation_note": generation_note,
        "request_parameters": endpoint.get("request_parameters", []),
        "response_parameters": endpoint.get("response_parameters", []),
        "request_example": endpoint.get("request_example", {}),
        "success_response_example": endpoint.get("success_response_example", {}),
        "error_response_example": endpoint.get("error_response_example", {}),
    }


def _infer_role(endpoint_path: str) -> str:
    lowered = endpoint_path.lower().rstrip("/")
    last = lowered.rsplit("/", 1)[-1]
    return ENDPOINT_ROLE_RULES.get(last, "supporting_endpoint")


def _case_authoring_rules(
    vendor: str, endpoints: list[dict[str, Any]], game_codes: list[dict[str, Any]]
) -> dict[str, Any]:
    endpoint_paths = [item.get("endpoint", "") for item in endpoints]
    game_code = _resolved_game_code(vendor, game_codes)
    default_test_account = _default_test_account(vendor)
    return {
        "precondition_template": [
            "1. launch game <gameCode>. If the vendor doc does not mention a gameCode, ask the user which gameCode should be used.",
            "2. url : use /game/url for launch-game fixed cases; otherwise use the target vendor endpoint.",
            f"3. test account: {default_test_account} unless the user confirms a different vendor-specific account.",
            "API request parameters:",
            "Paste the request fields required by the target url/endpoint.",
        ],
        "remarks_template": [
            "Paste the response structure required by the target url/endpoint.",
            "For launch-game fixed cases, remarks may differ from endpoint API cases.",
        ],
        "endpoint_role_guidance": [
            "Bet amount and win amount cases need stronger checks for integer and decimal precision limits.",
            "API parameter tests should respect each parameter type, such as String, int, BigDecimal.",
            "User behavior expected results depend on supported capabilities. For example, multiple_bets=true means two bets in the same round should both succeed; multiple_bets=false means the second bet should fail.",
            "Idempotency behavior affects transaction/reference-related scenarios.",
        ],
        "known_endpoint_paths": endpoint_paths,
        "default_test_account": default_test_account,
        "default_test_account_rule": "first 3 English letters of vendor name in lowercase + YYMMDD",
        "default_game_code": game_code,
        "game_code_source": _game_code_source(vendor, game_codes),
        "vendor": vendor,
    }


def _generation_mapping() -> dict[str, Any]:
    return {
        "strategy": (
            "Use category/capability to select reference knowledge, then use output_section "
            "to place generated cases into the fixed XMind structure."
        ),
        "knowledge_classification": {
            "primary_grouping": "category",
            "secondary_grouping": "vendor_capability",
            "endpoint_usage": (
                "Endpoints are supporting context for URL, role, parameters, and response structure. "
                "Do not select reference cases by endpoint name alone."
            ),
        },
        "mandatory_user_behavior_categories": [
            "launch_game",
            "balance",
            "bet",
            "settlement",
            "rollback",
            "amount_precision",
        ],
        "capability_specific_categories": [
            "multiple_bets",
            "multiple_settlements",
            "modify_settlement_adjustment",
            "settle_by_round_or_settle_by_bet",
            "rollback_bet",
            "rollback_settled_bet",
            "rollback_by_round_or_rollback_by_bet",
            "bet_and_settle",
            "rollback_bet_and_settle",
            "idempotency",
            "freespin",
            "jackpot",
        ],
        "knowledge_category_to_xmind_section": KNOWLEDGE_CATEGORY_TO_XMIND_SECTION,
        "generated_xmind_structure": GENERATED_XMIND_STRUCTURE,
        "generated_case_routing_fields": [
            "category",
            "output_section",
            "endpoint_group",
            "endpoints",
        ],
    }


def _pending_user_questions(vendor: str, game_codes: list[dict[str, Any]]) -> list[str]:
    questions = []
    if not _documented_game_codes(game_codes):
        questions.append(
            f"{vendor}: game code table is missing or blank. Current fallback is {_resolved_game_code(vendor, game_codes)}; please confirm which gameCode to use."
        )
    default_test_account = _default_test_account(vendor)
    questions.append(
        f"{vendor}: confirm whether test account {default_test_account} should be used, or provide a different test account."
    )
    return questions


def _supplementary_sources(vendor_dir: Path) -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for source_type, folder_name in (("pdf", "vendor_pdf"), ("url", "vendor_url")):
        source_dir = vendor_dir / folder_name
        manifest_path = source_dir / "manifest.json"
        index_path = source_dir / "endpoint_index.json"
        if not manifest_path.exists():
            continue
        manifest = _read_json(manifest_path)
        index = _read_json(index_path) if index_path.exists() else []
        sources[source_type] = {
            "folder": str(source_dir),
            "manifest": str(manifest_path),
            "endpoint_index": str(index_path) if index_path.exists() else "",
            "total_endpoints": manifest.get("total_endpoints", len(index)),
            "total_sections": manifest.get("total_sections", 0),
            "usage": "Read manifest and endpoint_index first, then load only selected sections/*.json.",
            "endpoints": [
                {
                    "api_name": item.get("api_name", ""),
                    "method": item.get("method", ""),
                    "endpoint": item.get("endpoint", ""),
                    "role": item.get("role", ""),
                    "section_file": item.get("section_file", ""),
                }
                for item in index
            ],
        }
    return sources


def _resolved_game_code(vendor: str, game_codes: list[dict[str, Any]]) -> str:
    documented = _documented_game_codes(game_codes)
    if documented:
        return documented[0]
    return FALLBACK_GAME_CODES.get(vendor, "")


def _default_test_account(vendor: str, today: date | None = None) -> str:
    current = today or date.today()
    letters = "".join(re.findall(r"[A-Za-z]", vendor or "")).lower()
    prefix = (letters[:3] or "ven").ljust(3, "x")
    return f"{prefix}{current:%y%m%d}"


def _game_code_source(vendor: str, game_codes: list[dict[str, Any]]) -> str:
    if _documented_game_codes(game_codes):
        return "vendor_doc_game_code_table"
    if FALLBACK_GAME_CODES.get(vendor):
        return "fallback_pending_user_confirmation"
    return "missing_pending_user_confirmation"


def _documented_game_codes(game_codes: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("game_code", "")).strip()
        for item in game_codes
        if str(item.get("game_code", "")).strip()
    ]


def _extract_game_codes_from_raw(vendor_dir: Path) -> list[dict[str, str]]:
    raw_path = vendor_dir / "raw_doc.json"
    if not raw_path.exists():
        return []
    raw = _read_json(raw_path)
    output = []
    for table in raw.get("tables", []):
        if not table:
            continue
        headers = [_normalize_header(cell) for cell in table[0]]
        if "game code" not in headers:
            continue
        code_index = headers.index("game code")
        type_index = headers.index("gametype") if "gametype" in headers else None
        name_index = headers.index("game name") if "game name" in headers else None
        for row in table[1:]:
            if len(row) <= code_index:
                continue
            output.append(
                {
                    "game_type": row[type_index].strip()
                    if type_index is not None and len(row) > type_index
                    else "",
                    "game_name": row[name_index].strip()
                    if name_index is not None and len(row) > name_index
                    else "",
                    "game_code": row[code_index].strip(),
                }
            )
    return output


def _normalize_header(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)
