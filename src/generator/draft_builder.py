"""Build a Codex-facing draft JSON scaffold for new vendor test case generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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


def build_draft(vendor: str, vendor_detail_root: Path, output_root: Path) -> Path:
    vendor_dir = Path(vendor_detail_root) / vendor
    if not vendor_dir.exists():
        raise FileNotFoundError(f"Vendor detail folder does not exist: {vendor_dir}")

    capability_profile = _read_json(vendor_dir / "capability_profile.json")
    endpoints = _read_json(vendor_dir / "endpoints.json")
    error_codes = _read_json(vendor_dir / "error_codes.json")
    checklist_path = vendor_dir / "vendor_master_checklist.json"
    checklist = _read_json(checklist_path) if checklist_path.exists() else []

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
        "endpoint_roles": [_endpoint_role(endpoint) for endpoint in endpoints],
        "error_codes": error_codes,
        "case_authoring_rules": _case_authoring_rules(vendor, endpoints),
        "pending_user_questions": _pending_user_questions(vendor, endpoints),
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
    }


def _infer_role(endpoint_path: str) -> str:
    lowered = endpoint_path.lower().rstrip("/")
    last = lowered.rsplit("/", 1)[-1]
    return ENDPOINT_ROLE_RULES.get(last, "supporting_endpoint")


def _case_authoring_rules(vendor: str, endpoints: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint_paths = [item.get("endpoint", "") for item in endpoints]
    return {
        "precondition_template": [
            "1. launch this vendor's gameCode. If the vendor doc does not mention a gameCode, ask the user which gameCode/account should be used.",
            "2. url : use /game/url for launch-game fixed cases; otherwise use the target vendor endpoint.",
            "3. test account: egt260514 unless the user confirms a different vendor-specific account.",
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
        "default_test_account": "egt260514",
        "vendor": vendor,
    }


def _pending_user_questions(vendor: str, endpoints: list[dict[str, Any]]) -> list[str]:
    questions = []
    if not _has_game_code_hint(endpoints):
        questions.append(
            f"{vendor}: vendor doc did not provide a clear gameCode for launch-game preconditions. Please confirm which gameCode to use."
        )
    questions.append(
        f"{vendor}: confirm whether test account egt260514 should be used, or provide a different test account."
    )
    return questions


def _has_game_code_hint(endpoints: list[dict[str, Any]]) -> bool:
    text = json.dumps(endpoints, ensure_ascii=False).lower()
    return "gamecode" in text or "game code" in text


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)
