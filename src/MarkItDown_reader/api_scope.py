"""Evidence-based classification and project-scope selection for API operations."""
from __future__ import annotations

import json
import re


CORE_ROLES = ("authentication", "balance", "bet", "settlement")
CONDITIONAL_ROLES = ("token_refresh", "terminate_session", "rollback",
                     "round_finalization", "promotional_payout")
TARGET_ROLES = CORE_ROLES + CONDITIONAL_ROLES

ROLE_USAGE = {
    "authentication": "Game launch/session entry: validate the launch/player credential and establish the authenticated game session; returned credentials are vendor-defined.",
    "token_refresh": "Conditional credential renewal: obtain a fresh credential/code, then follow the vendor-documented authentication sequence.",
    "terminate_session": "Session lifecycle: notify the vendor when the player session/game ends, when this callback is provided.",
    "balance": "Game entry and balance checks: obtain the player's wallet balance for the active session.",
    "bet": "Gameplay debit: record the player's wager/stake against the wallet.",
    "settlement": "Bet payout: credit the result/winnings after a successful bet, when a settlement callback exists.",
    "rollback": "Conditional recovery: reverse/refund the original bet when the bet transaction fails or is rolled back.",
    "round_finalization": "Conditional round lifecycle: close the game round and finalize its transactions after the round's wallet actions.",
    "promotional_payout": "Conditional promotional payout: credit a promotion award; this flow may pay without a preceding Bet call.",
}

FLOW = [
    {"roles": ["token_refresh", "authentication"], "order": "vendor_documented",
     "condition": "vendors differ on whether credential issuance precedes or follows authentication; use the source-defined sequence"},
    {"from": "authentication", "to": "balance", "condition": "game entry/session established"},
    {"from": "authentication", "to": "bet", "condition": "active authenticated game session"},
    {"from": "bet", "to": "settlement", "condition": "bet succeeds and has a payout/result"},
    {"from": "bet", "to": "rollback", "condition": "bet fails or requires reversal; reference the original bet"},
    {"from": "authentication", "to": "terminate_session", "condition": "session/game ends"},
    {"from": "bet", "to": "round_finalization", "condition": "round closes after a non-winning or debit transaction; finalize the round"},
    {"from": "settlement", "to": "round_finalization", "condition": "round closes after payout; finalize the round"},
    {"from": "authentication", "to": "promotional_payout", "condition": "a promotion award is payable; a Bet call is not required"},
]


def _plain(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value or "")
    return re.sub(r"[`*_{}]", " ", value).lower()


def _param_names(op: dict) -> set[str]:
    names = set()
    for item in op.get("parameters", []):
        names.add(str(item.get("name", "")).lower())
        try:
            raw = json.loads(item.get("raw", "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(raw, dict):
            names.add(str(raw.get("name", "")).lower())
    return names


def _classify_adjustment(op: dict) -> dict:
    """Classify an adjustment only when the source provides directional evidence.

    A vendor's ``Revision`` label is not enough to decide whether the change
    modifies a bet/debit or a settlement/credit. Keep ambiguous revisions
    explicit so downstream case generation can require review instead of
    silently treating them as rollbacks.
    """
    title = _plain(op.get("operation_name", ""))
    path = _plain(op.get("url_or_path", ""))
    action = _plain((op.get("discriminator") or {}).get("value", ""))
    logic = _plain(op.get("logic", ""))
    text = f"{title} {path} {action} {logic}"
    labelled_adjustment = re.search(r"\b(adjust(?:ment|ed|ing)?|revision)\b", title)
    documented_adjustment = re.search(r"\badjust(?:ment|ed|ing)?\b", text)
    if not labelled_adjustment and not documented_adjustment:
        return {"type": "not_applicable", "candidates": [], "basis": []}

    bet_evidence = re.findall(
        r"\b(?:bet|debit|wager|stake)\b.{0,45}\badjust(?:ment|ed|ing)?\b|"
        r"\badjust(?:ment|ed|ing)?\b.{0,45}\b(?:bet|debit|wager|stake)\b",
        text,
    )
    settlement_evidence = re.findall(
        r"\b(?:settlement|settle|credit|payout|win|winning|result)\b.{0,45}\badjust(?:ment|ed|ing)?\b|"
        r"\badjust(?:ment|ed|ing)?\b.{0,45}\b(?:settlement|settle|credit|payout|win|winning|result)\b",
        text,
    )
    rollback_evidence = re.findall(
        r"\b(?:rollback|reverse|cancel|void|refund)\b.{0,45}\badjust(?:ment|ed|ing)?\b|"
        r"\badjust(?:ment|ed|ing)?\b.{0,45}\b(?:rollback|reverse|cancel|void|refund)\b",
        text,
    )
    if re.search(r"\b(?:rollback|reverse|cancel|void|refund)\s+adjust(?:ment|ed|ing)?\b", text):
        return {"type": "rollback_adjustment", "candidates": ["rollback_adjustment"],
                "basis": rollback_evidence}
    directional = [
        ("bet_adjustment", bet_evidence),
        ("settlement_adjustment", settlement_evidence),
        ("rollback_adjustment", rollback_evidence),
    ]
    candidates = [name for name, basis in directional if basis]
    if len(candidates) == 1:
        name = candidates[0]
        basis = next(basis for candidate, basis in directional if candidate == name)
        return {"type": name, "candidates": [name], "basis": basis}
    if candidates:
        return {"type": "ambiguous", "candidates": candidates,
                "basis": [item for _, basis in directional for item in basis]}

    ambiguous_signals = []
    if re.search(r"\b(?:increase|decrease|add|deduct|subtract)\b.{0,60}\b(?:balance|amount|player)\b", text):
        ambiguous_signals.append("source describes balance/amount changes")
    if re.search(r"\bbetstatus\b|\bbet\s+result\b|\bwin\b", text):
        ambiguous_signals.append("source references bet result state")
    if title.strip() == "revision" or "revision" in title:
        ambiguous_signals.append("operation is labelled Revision")
    if ambiguous_signals:
        return {"type": "ambiguous", "candidates": ["bet_adjustment", "settlement_adjustment", "rollback_adjustment"],
                "basis": ambiguous_signals}
    return {"type": "unknown", "candidates": ["bet_adjustment", "settlement_adjustment", "rollback_adjustment"],
            "basis": ["adjustment is documented without directional evidence"]}


def _role_scores(op: dict) -> tuple[dict[str, int], dict[str, list[str]]]:
    title = _plain(op.get("operation_name", ""))
    path = _plain(op.get("url_or_path", ""))
    logic = _plain(op.get("logic", ""))
    discriminator = op.get("discriminator") or {}
    action = _plain(discriminator.get("value", "")) if isinstance(discriminator, dict) else ""
    text = f"{title} {path} {action} {logic}"
    names = _param_names(op)
    adjustment_type = _classify_adjustment(op)["type"]
    scores = {role: 0 for role in TARGET_ROLES}
    clues = {role: [] for role in TARGET_ROLES}

    def add(role, points, clue):
        scores[role] += points
        clues[role].append(clue)

    # Explicit endpoint names/path segments carry the strongest signal.
    if re.search(r"\b(auth|auth\s+token|authenticate|authentication|authorize|authorization|login)\b", f"{title} {path} {action}"):
        add("authentication", 7, "operation name/path identifies authentication")
    elif re.search(r"\b(authenticate|authentication|authorize|authorization|validate|verify)\b.{0,60}\b(player|account|session|token|credential)\b|\b(player|account|session|token|credential)\b.{0,60}\b(authenticate|authentication|authorize|authorization|validate|verify)\b", logic):
        add("authentication", 4, "description says the operation authenticates a player/account")

    if re.search(r"\b(defen[cs]e[ -]?code|refresh[ -]?(?:token|credential)|renew[ -]?(?:token|credential))\b", f"{title} {path} {action}"):
        add("token_refresh", 7, "operation name/path identifies credential refresh")
    elif re.search(r"\b(new|fresh|refresh|renew|generate|issue)\b.{0,45}\b(defen[cs]e[ -]?code|token|credential)\b", logic):
        add("token_refresh", 4, "description says it issues or renews a credential")
    if "defencecode" in names or "defensecode" in names:
        add("token_refresh", 1, "request/response contains a defence-code field")
    if re.search(r"followed by (?:a )?new authenticate|then authenticate|authenticate call", logic):
        add("token_refresh", 2, "document links the new credential to a following authentication call")

    if re.search(r"\b(terminate|termination|logout|logoff|end session|close session|session expired|session expiration)\b", f"{title} {path} {action}"):
        add("terminate_session", 7, "operation name/path identifies session termination")
    elif re.search(r"\b(notify|inform)\b.{0,70}\b(session|player session)\b.{0,40}\b(finish|end|terminat|clos)\w*", logic):
        add("terminate_session", 4, "description says it notifies session completion")

    if re.search(r"\b(end round|round finali[sz]ation|round close|close round)\b", f"{title} {path} {action}"):
        add("round_finalization", 7, "operation name/path identifies round closure or finalization")
    elif re.search(r"\b(finali[sz]e|close|complete)\b.{0,60}\b(round|game transactions?)\b", logic):
        add("round_finalization", 4, "description says it closes a round or finalizes game transactions")

    if re.search(r"\b(promo\s*win|promotional payout|promotion payout)\b", f"{title} {path} {action}"):
        add("promotional_payout", 7, "operation name/path identifies a promotion payout")
    elif re.search(r"\b(promotion|campaign|tournament)\b.{0,80}\b(payout|credit|cash balance|award)\b", logic):
        add("promotional_payout", 4, "description identifies a promotional wallet credit")

    if re.search(r"\b(balance|wallet balance|getbalance)\b", f"{title} {path} {action}"):
        add("balance", 7, "operation name/path identifies a balance query")
    elif re.search(r"\b(get|obtain|retrieve|query|check)\b.{0,45}\b(player|wallet|account)?\s*balance\b", logic):
        add("balance", 4, "description says it retrieves/checks a balance")

    if re.search(r"\b(bet|wager|debit|stake)\b", f"{title} {path} {action}"):
        add("bet", 7, "operation name/path identifies a wager/debit")
    elif re.search(r"\b(withdraw|debit)\b", f"{title} {path}"):
        transaction_fields = {"roundnumber", "roundid", "gamekey", "gameid", "transferid"} & names
        debit_text = bool(re.search(r"\b(withdraw|debit)\b.{0,60}\b(fund|player account|wallet|bet|wager)\b", logic))
        if transaction_fields and debit_text:
            add("bet", 6, "withdraw/debit operation has game-transaction fields and debits player funds")
        elif transaction_fields:
            add("bet", 3, "withdraw/debit operation has game-transaction fields")
    elif re.search(r"\b(place|accept|process|deduct|debit|subtract)\b.{0,55}\b(bet|wager|stake|funds|balance)\b", logic):
        transaction_fields = {"roundnumber", "roundid", "gamekey", "gameid", "transferid"} & names
        if transaction_fields:
            add("bet", 5, "description and game-transaction fields identify a wager debit")
        else:
            add("bet", 3, "description may describe a wager debit")

    # Promotional/award APIs are purposefully kept out of wallet settlement.
    promotional = bool(re.search(r"\b(award|campaign|promotion|tournament|jackpot contribution)\b", f"{title} {path}"))
    if not promotional:
        if re.search(r"\b(deposit|settlement|settle|credit|payout|winnings?|result)\b", f"{title} {path} {action}"):
            add("settlement", 7, "operation name/path identifies a wallet settlement/payout")
        elif re.search(r"\b(credit|deposit|pay|settle)\b.{0,65}\b(player|wallet|account|winnings?|win|transaction)\b", logic):
            transaction_fields = {"roundnumber", "roundid", "transferid"} & names
            add("settlement", 5 if transaction_fields else 3,
                "description and transaction fields identify a wallet payout" if transaction_fields
                else "description may describe a wallet payout")
        if ("roundnumber" in names or "roundid" in names) and ("transferid" in names or "amount" in names):
            add("settlement", 1, "request includes round/transfer amount fields")

    if adjustment_type in {"bet_adjustment", "settlement_adjustment", "ambiguous", "unknown"}:
        # An adjustment is not automatically a rollback. Its eventual bet vs
        # settlement meaning is carried in the adjustment metadata and may
        # require endpoint/variant context before selecting a role.
        pass
    elif re.search(r"\b(reverse|rollback|refund|cancel|void)\b", f"{title} {path} {action}"):
        add("rollback", 7, "operation name/path identifies reversal/refund")
    elif re.search(r"\b(reverse|rollback|refund|cancel|void)\b.{0,60}\b(bet|wager|withdraw|transaction|transfer)\b", logic):
        transaction_fields = {"referenceid", "originaltransactionid", "originaltransferid", "transferid"} & names
        add("rollback", 5 if transaction_fields else 3,
            "description and reference fields identify transaction reversal" if transaction_fields
            else "description may describe transaction reversal")
    if {"referenceid", "transferid"} <= names and ("roundnumber" in names or "roundid" in names):
        add("rollback", 2, "request links a reversal to an original game transaction")

    if re.search(r"\b(?:bet\s+and\s+(?:result|win)|bet\s*/\s*result|betresult)\b", f"{title} {path} {action}"):
        add("settlement", 7, "combined bet-and-result operation credits the payout in the same wallet call")
    return scores, clues


def classify_and_select(doc: dict) -> dict:
    """Annotate every discovered operation; retain candidates outside the use-case scope."""
    for op in doc["operations"]:
        op["adjustment"] = _classify_adjustment(op)
        scores, clues = _role_scores(op)
        combined_bet_result = bool(re.search(
            r"\b(?:bet\s+and\s+(?:result|win)|bet\s*/\s*result|betresult)\b",
            f"{_plain(op.get('operation_name', ''))} {_plain(op.get('url_or_path', ''))}"))
        explicit_rollback = bool(re.search(
            r"\b(?:rollback|reverse|refund|cancel|void)\b",
            f"{_plain(op.get('operation_name', ''))} {_plain(op.get('url_or_path', ''))}"))
        best_role = ("settlement" if combined_bet_result else
                     "rollback" if explicit_rollback and scores["rollback"] >= 7 and scores["settlement"] < 7 else
                     max(TARGET_ROLES, key=lambda role: scores[role]))
        best_score = scores[best_role]
        role = best_role if best_score >= 3 else None
        category = _out_of_scope_category(op)
        if role:
            op["role"] = role
            op["role_confidence"] = "high" if best_score >= 7 else "medium" if best_score >= 5 else "low"
            op["role_score"] = best_score
            op["role_basis"] = clues[role]
            op["usage_logic"] = ROLE_USAGE[role]
            in_scope = best_score >= 5 and category is None
            op["selection_status"] = "selected" if in_scope else "excluded" if category else "needs_review"
            if in_scope:
                op["selection_reason"] = f"Matched in-scope role '{role}' from document evidence."
            elif category:
                op["selection_reason"] = f"Recognized as '{category}', outside the configured game-wallet callback scope."
            else:
                op["selection_reason"] = f"Possible '{role}' match, but evidence is too weak for automatic inclusion."
            # Classification is an evidence-backed interpretation; point it at source evidence.
            source_ref = next(iter(op.get("evidence", {}).get("operation_name", [])), None)
            if source_ref:
                op.setdefault("evidence", {})["role"] = [source_ref]
        else:
            op["role"] = None
            op["role_confidence"] = "none"
            op["role_score"] = 0
            op["role_basis"] = []
            op["usage_logic"] = "No target wallet role was established from the available endpoint evidence."
            op["selection_status"] = "excluded"
            op["selection_reason"] = (f"Recognized as '{category}', outside the configured game-wallet callback scope."
                                       if category else "No target wallet role was established from the available endpoint evidence.")
        op["in_scope"] = bool(role and best_score >= 5 and category is None)
        op["scope_category"] = category or ("game_wallet_callback" if op["in_scope"] else "unclassified")

    selected_roles = {op["role"] for op in doc["operations"] if op.get("in_scope")}
    # A combined Bet/Result endpoint implements both sides of the wallet flow.
    if any(op.get("in_scope") and re.search(
            r"\b(?:bet\s+and\s+(?:result|win)|bet\s*/\s*result|betresult)\b",
            f"{_plain(op.get('operation_name', ''))} {_plain(op.get('url_or_path', ''))}")
            for op in doc["operations"]):
        selected_roles.update({"bet", "settlement"})
    # Some wallet APIs return the current balance as part of authentication
    # instead of exposing a separate balance endpoint. Treat that documented
    # response capability as satisfying the balance role without inventing a
    # second endpoint.
    if "balance" not in selected_roles and any(
        op.get("in_scope")
        and op.get("role") == "authentication"
        and re.search(r"\bbalance\b", _plain(op.get("logic", "")))
        for op in doc["operations"]
    ):
        selected_roles.add("balance")
    doc["extensions"]["endpoint_selection"] = {
        "profile": "game_wallet_flow/v1",
        "scope_roles": list(TARGET_ROLES),
        "core_roles": list(CORE_ROLES),
        "conditional_roles": list(CONDITIONAL_ROLES),
        "flow": FLOW,
        "selected_operation_ids": [op["operation_id"] for op in doc["operations"] if op.get("in_scope")],
        "missing_core_roles": [role for role in CORE_ROLES if role not in selected_roles],
        "missing_conditional_roles": [role for role in CONDITIONAL_ROLES if role not in selected_roles],
        "selection_rule": "Select evidence-supported operations matching a configured game-wallet role; promotional payouts may occur without Bet, and round finalization is selected when documented. Retain other candidates as excluded or needs_review.",
    }
    return doc


def _out_of_scope_category(op: dict) -> str | None:
    text = f"{_plain(op.get('operation_name', ''))} {_plain(op.get('url_or_path', ''))}"
    if re.search(r"\bpromo\s*win\b", text):
        return None  # A documented promotional payout is an in-scope conditional wallet flow.
    rules = (
        (r"\b(?:cwguestlogin|cwstartgamev?2?)\.do\b", "game_launch_portal"),
        (r"\b(bet tier|bet tiers|bet configuration|wager configuration)\b", "game_configuration"),
        (r"\b(client portal|game/url|game url)\b", "game_launch_portal"),
        (r"\b(campaign|gift spin)\b", "campaign_management"),
        (r"\b(tournament)\b", "tournament"),
        (r"\b(contribution|jackpot)\b", "jackpot_service"),
        (r"\b(history|match/details|reconciliation)\b", "history_or_reporting"),
        (r"\b(award|awarding|promotion|bonus campaign|item award|gift ?win)\b", "optional_award"),
    )
    for pattern, category in rules:
        if re.search(pattern, text):
            return category
    return None
