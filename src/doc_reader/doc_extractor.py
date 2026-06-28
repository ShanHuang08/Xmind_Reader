"""Extract AI-friendly vendor API details from parsed documents."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


CAPABILITY_RULES: dict[str, tuple[str, ...]] = {
    "multiple_bets": ("multiple bet", "multiple bets", "same round", "multi bet"),
    "multiple_settlements": ("multiple settlement", "multiple settlements", "settle twice"),
    "rollback_settlements": ("rollback", "roll back"),
    "modify_settlements_adjustment": ("adjustment", "modify settlement", "adjust settlement"),
    "cancel_bet": ("cancel bet", "cancel transaction", "refund"),
    "free_spin": ("free spin", "freespin", "free game"),
    "jackpot": ("jackpot",),
    "idempotency": ("idempotency", "duplicate", "same transaction"),
    "retry": ("retry", "re-try"),
    "wallet": ("wallet", "balance", "cash"),
}

CHECKLIST_CAPABILITY_MAP: dict[str, str] = {
    "Freespin": "free_spin",
    "Jackpot": "jackpot",
    "Multiple Bet": "multiple_bets",
    "Multiple Win": "multiple_settlements",
    "Refund unsettle bet": "cancel_bet",
    "Cancel settled bet": "rollback_settlements",
    "Adjustment": "modify_settlements_adjustment",
    "Process Endround": "process_endround",
}

ENDPOINT_RE = re.compile(r"(?i)\b(?:GET|POST|PUT|PATCH|DELETE)?\s*(/api/[A-Za-z0-9_./{}?=&:-]+)")
ERROR_CODE_RE = re.compile(r"\b(?:code|error|status)[\s:=\"]+([A-Z_]*\d{2,}|[A-Z_]{3,})", re.I)


def extract_vendor_detail(parsed: dict[str, Any], vendor_name: str) -> dict[str, Any]:
    text = parsed.get("plain_text", "")
    sections = _sections(parsed.get("paragraphs", []))
    endpoints = _extract_endpoints(parsed, sections)
    error_codes = _extract_error_codes(parsed, text)
    for endpoint in endpoints:
        _attach_endpoint_examples(endpoint, error_codes)
    checklist = _extract_vendor_master_checklist(parsed)
    game_codes = _extract_game_codes(parsed)
    profile = _capability_profile(vendor_name, text, endpoints, checklist)
    return {
        "vendor": vendor_name,
        "source_file": parsed.get("source_file", ""),
        "title": parsed.get("title", ""),
        "sections": sections,
        "endpoints": endpoints,
        "error_codes": error_codes,
        "capability_profile": profile,
        "vendor_master_checklist": checklist,
        "game_codes": game_codes,
        "tables": parsed.get("tables", []),
        "tables_detailed": parsed.get("tables_detailed", []),
        "links": parsed.get("links", []),
    }


def _sections(paragraphs: list[dict[str, str]]) -> list[dict[str, Any]]:
    sections = []
    current = {"title": "Overview", "level": 1, "content": []}
    for paragraph in paragraphs:
        style = paragraph.get("style", "").lower()
        text = paragraph.get("text", "")
        if style in {"h1", "h2", "h3", "h4"} or style.startswith("heading"):
            if current["content"]:
                sections.append(current)
            level = int(style[1]) if style.startswith("h") and style[1:].isdigit() else 2
            current = {"title": text, "level": level, "content": []}
        else:
            current["content"].append(text)
    if current["content"] or current["title"] != "Overview":
        sections.append(current)
    return sections


def _extract_endpoints(parsed: dict[str, Any], sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    endpoints: dict[str, dict[str, Any]] = {}
    full_text = parsed.get("plain_text", "")
    parameter_tables = _endpoint_parameter_tables(parsed, sections)
    for section in sections:
        section_text = "\n".join(section.get("content", []))
        for endpoint in ENDPOINT_RE.findall(section_text):
            context = _context_around(full_text, endpoint)
            endpoints.setdefault(
                endpoint,
                {
                    "endpoint": endpoint,
                    "section": section.get("title", ""),
                    "methods": _methods_near_endpoint(context, endpoint),
                    "keywords": _merge_keywords(
                        _endpoint_keywords(endpoint), _endpoint_keywords(context or endpoint)
                    ),
                },
            )
            endpoints[endpoint].update(parameter_tables.get(endpoint, {}))

    for table in parsed.get("tables", []):
        for row in table:
            row_text = " ".join(row)
            for endpoint in ENDPOINT_RE.findall(row_text):
                context = _context_around(full_text, endpoint) or row_text
                endpoints.setdefault(
                    endpoint,
                    {
                        "endpoint": endpoint,
                        "section": "table",
                        "methods": _methods_near_endpoint(context, endpoint),
                        "keywords": _merge_keywords(
                            _endpoint_keywords(endpoint), _endpoint_keywords(context or endpoint)
                        ),
                    },
                )
                endpoints[endpoint].update(parameter_tables.get(endpoint, {}))
    return sorted(endpoints.values(), key=lambda item: item["endpoint"])


def _endpoint_parameter_tables(
    parsed: dict[str, Any], sections: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    tables = [table for table in parsed.get("tables", []) if _is_parameter_table(table)]
    cursor = 0
    by_endpoint: dict[str, dict[str, Any]] = {}
    for section in sections:
        endpoint = _endpoint_from_section_title(section.get("title", ""))
        if not endpoint:
            continue
        entry: dict[str, Any] = {}
        if cursor < len(tables):
            entry["request_parameters"] = _parameter_rows(tables[cursor])
            cursor += 1
        if cursor < len(tables):
            entry["response_parameters"] = _parameter_rows(tables[cursor])
            cursor += 1
        by_endpoint[endpoint] = entry
    return by_endpoint


def _endpoint_from_section_title(title: str) -> str:
    match = ENDPOINT_RE.search(title or "")
    return match.group(1) if match else ""


def _is_parameter_table(table: list[list[str]]) -> bool:
    if not table:
        return False
    headers = [_normalize_header(cell) for cell in table[0]]
    return {"parameter", "type"}.issubset(set(headers))


def _parameter_rows(table: list[list[str]]) -> list[dict[str, str]]:
    headers = [_normalize_header(cell) for cell in table[0]]
    rows = []
    for row in table[1:]:
        item = {}
        for index, header in enumerate(headers):
            if index >= len(row):
                continue
            key = {
                "parameter": "name",
                "type": "type",
                "require": "required",
                "description": "description",
                "remark": "remark",
            }.get(header, header.replace(" ", "_"))
            item[key] = row[index]
        if item.get("name"):
            rows.append(item)
    return rows


def _attach_endpoint_examples(endpoint: dict[str, Any], error_codes: list[dict[str, str]]) -> None:
    request_parameters = endpoint.get("request_parameters", [])
    response_parameters = endpoint.get("response_parameters", [])
    if request_parameters:
        endpoint["request_example"] = _example_object(request_parameters, include_optional=False)
    if response_parameters:
        endpoint["success_response_example"] = _example_object(
            response_parameters,
            include_optional=False,
            response_mode=True,
        )
        endpoint["error_response_example"] = _error_response_example(error_codes)


def _example_object(
    parameters: list[dict[str, str]],
    include_optional: bool = False,
    response_mode: bool = False,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for parameter in parameters:
        if not _include_example_parameter(parameter, include_optional=include_optional):
            continue
        name = str(parameter.get("name", "")).strip()
        if not name:
            continue
        value = _example_value(parameter, response_mode=response_mode)
        _set_nested_value(output, name, value)
    return output


def _include_example_parameter(parameter: dict[str, str], include_optional: bool = False) -> bool:
    name = str(parameter.get("name", "")).strip().lower()
    description = str(parameter.get("description", "")).strip().lower()
    required = str(parameter.get("required", "")).strip().upper()

    if name in {"token", "data/token"}:
        return True
    if name == "type" and "only in credit" in description:
        return False
    if not include_optional and required in {"N", "NO", "FALSE", "0"}:
        return False
    return True


def _set_nested_value(output: dict[str, Any], name: str, value: Any) -> None:
    parts = [part for part in name.split("/") if part]
    if not parts:
        return
    current = output
    for part in parts[:-1]:
        if not isinstance(current.get(part), dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _example_value(parameter: dict[str, str], response_mode: bool = False) -> Any:
    name = str(parameter.get("name", "")).lower()
    param_type = str(parameter.get("type", "")).lower()
    description = str(parameter.get("description", "")).lower()
    text = " ".join([name, param_type, description])

    if response_mode:
        if name == "result":
            return "OK"
        if name == "timestamp":
            return "20250825T163933Z"
        if name.endswith("accountbalance") or name.endswith("accountfreebalance"):
            return 999999
        if name.endswith("accountcurrency"):
            return "USD"
        if name.endswith("transactionid"):
            return "78ba204111ce"
        if name.endswith("token"):
            return "99aa356-2x99"
        if param_type == "json":
            return {}

    if name == "sessionid":
        return "7481b6cb-6aa3-46dc-a131-aea2d2a4797c"
    if name == "hash":
        return "validhashvalue"
    if name == "amount":
        return 10
    if name == "gamename":
        return "Burning Slot 40"
    if name == "gameid":
        return "LUCKYFRUITZ"
    if name == "transactionid":
        return "D4330252729-4459762329"
    if name == "playid":
        return "4330252729"
    if name == "operation":
        return "DEBIT"
    if name == "gamemode":
        return "REAL"
    if name == "userid":
        return "sampleUser78"
    if name == "amountcurrency" or "currency" in text:
        return "USD"
    if name == "token":
        return "r9CfvbG7B5NylcuDZb24"
    if name == "playstatus":
        return "1"
    if name == "rounddetails":
        return "Spin"
    if name == "description":
        return "OK"
    if "url" in name or "url" in description:
        return "https://example.com/replay/4330252729"
    if "numeric string" in param_type:
        return "10"
    if name.endswith("id") or " identifier" in description or " id" in description:
        return f"{parameter.get('name', 'id')}_001"
    if "amount" in text:
        return 10
    if "timestamp" in text or "time" in text:
        return "20250825T163933Z"
    if "int" in param_type or "long" in param_type:
        return 1
    return f"sample_{parameter.get('name', 'value')}"


def _error_response_example(error_codes: list[dict[str, str]]) -> dict[str, Any]:
    selected = _select_error_code(error_codes)
    return {
        "result": "ERROR",
        "timestamp": "20110322T152403Z",
        "error": {
            "code": selected.get("code", "ERROR"),
            "message": selected.get("context", "Error"),
        },
    }


def _select_error_code(error_codes: list[dict[str, str]]) -> dict[str, str]:
    for item in error_codes:
        context = str(item.get("context", "")).lower()
        if "insufficient funds" in context:
            return item
    for item in error_codes:
        code = str(item.get("code", "")).strip()
        context = str(item.get("context", "")).lower()
        if code and code != "0" and "success" not in context:
            return item
    return {"code": "ERROR", "context": "Error"}


def _extract_error_codes(parsed: dict[str, Any], text: str) -> list[dict[str, str]]:
    found: dict[str, str] = {}
    for table in parsed.get("tables", []):
        if not table:
            continue
        headers = [cell.strip().lower() for cell in table[0]]
        if "code" in headers and any(header in headers for header in ("message", "description")):
            code_index = headers.index("code")
            message_index = headers.index("message") if "message" in headers else headers.index("description")
            exception_index = headers.index("related exceptions") if "related exceptions" in headers else None
            for row in table[1:]:
                if len(row) <= max(code_index, message_index):
                    continue
                code = row[code_index].strip()
                if not re.fullmatch(r"\d{1,6}", code):
                    continue
                context = row[message_index].strip()
                if exception_index is not None and len(row) > exception_index and row[exception_index].strip():
                    context = f"{context} | {row[exception_index].strip()}"
                found.setdefault(code, context)

    if found:
        return [{"code": code, "context": context} for code, context in sorted(found.items(), key=lambda item: int(item[0]))]

    for match in ERROR_CODE_RE.finditer(text):
        code = match.group(1)
        if not re.fullmatch(r"\d{1,6}", code):
            continue
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 180)
        found.setdefault(code, text[start:end].replace("\n", " ").strip())

    return [{"code": code, "context": context} for code, context in sorted(found.items(), key=lambda item: int(item[0]))]


def _capability_profile(
    vendor_name: str,
    text: str,
    endpoints: list[dict[str, Any]],
    checklist: list[dict[str, Any]],
) -> dict[str, Any]:
    lowered = text.lower()
    supports = {
        capability: any(keyword in lowered for keyword in keywords)
        for capability, keywords in CAPABILITY_RULES.items()
    }
    supports_source = {capability: "keyword" for capability in supports}
    for item in checklist:
        capability = item.get("capability_key")
        if not capability or item.get("enabled") is None:
            continue
        supports[capability] = bool(item["enabled"])
        supports_source[capability] = "vendor_master_checklist"

    endpoint_keywords = Counter(
        keyword for endpoint in endpoints for keyword in endpoint.get("keywords", [])
    )
    return {
        "vendor": vendor_name,
        "supports": supports,
        "supports_source": supports_source,
        "vendor_master_checklist": checklist,
        "detected_endpoint_keywords": dict(sorted(endpoint_keywords.items())),
        "endpoint_count": len(endpoints),
    }


def _extract_vendor_master_checklist(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    tables = parsed.get("tables", [])
    output = []
    for table in tables:
        if not table:
            continue
        headers = [_normalize_header(cell) for cell in table[0]]
        if "name" not in headers or not any("enable" in header for header in headers):
            continue
        name_index = headers.index("name")
        description_index = headers.index("description") if "description" in headers else None
        remark_index = headers.index("remark") if "remark" in headers else None
        enable_index = next(index for index, header in enumerate(headers) if "enable" in header)
        for row in table[1:]:
            if len(row) <= max(name_index, enable_index):
                continue
            name = row[name_index].strip()
            if (
                not name
                or name
                in {"Result Type", "Operator Endpoint", "Vendor Endpoint", "Process Endround"}
                or "Threshold" in name
            ):
                continue
            enabled = _enabled_value(row[enable_index] if len(row) > enable_index else "")
            output.append(
                {
                    "name": name,
                    "description": row[description_index].strip()
                    if description_index is not None and len(row) > description_index
                    else "",
                    "remark": row[remark_index].strip()
                    if remark_index is not None and len(row) > remark_index
                    else "",
                    "enabled": enabled,
                    "capability_key": CHECKLIST_CAPABILITY_MAP.get(name, ""),
                }
            )
    return output


def _extract_game_codes(parsed: dict[str, Any]) -> list[dict[str, str]]:
    output = []
    for table in parsed.get("tables", []):
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
            item = {
                "game_type": row[type_index].strip()
                if type_index is not None and len(row) > type_index
                else "",
                "game_name": row[name_index].strip()
                if name_index is not None and len(row) > name_index
                else "",
                "game_code": row[code_index].strip(),
            }
            if item["game_name"] or item["game_code"]:
                output.append(item)
    return output


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _enabled_value(value: str) -> bool | str | None:
    normalized = (value or "").strip().lower()
    if normalized == "checked":
        return True
    if normalized == "unchecked":
        return False
    if normalized in {"y", "yes", "true", "1", "enabled"}:
        return True
    if normalized in {"n", "no", "false", "0", "disabled"}:
        return False
    return value.strip() if value.strip() else None


def _capability_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return key or "unknown"


def _methods_near_endpoint(text: str, endpoint: str) -> list[str]:
    methods = []
    pattern = re.compile(rf"(?i)\b(GET|POST|PUT|PATCH|DELETE)\b\s*{re.escape(endpoint)}")
    methods.extend(match.group(1).upper() for match in pattern.finditer(text))
    return sorted(set(methods))


def _context_around(text: str, needle: str, radius: int = 700) -> str:
    index = text.find(needle)
    if index < 0:
        return ""
    return text[max(0, index - radius) : min(len(text), index + len(needle) + radius)]


def _endpoint_keywords(text: str) -> list[str]:
    keywords = []
    lowered = text.lower()
    for keyword in (
        "balance",
        "bet",
        "settle",
        "result",
        "rollback",
        "cancel",
        "auth",
        "token",
        "jackpot",
        "free spin",
        "adjustment",
    ):
        if keyword in lowered:
            keywords.append(keyword.replace(" ", "_"))
    return keywords


def _merge_keywords(primary: list[str], secondary: list[str]) -> list[str]:
    merged = []
    for keyword in primary + secondary:
        if keyword not in merged:
            merged.append(keyword)
    return merged
