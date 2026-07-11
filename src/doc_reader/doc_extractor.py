"""Extract AI-friendly vendor API details from parsed documents."""

from __future__ import annotations

import re
import json
from collections import Counter
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, urlsplit


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
    endpoint_examples = _endpoint_json_examples(sections)
    for endpoint in endpoints:
        _attach_endpoint_examples(endpoint, error_codes, endpoint_examples.get(endpoint.get("endpoint", ""), {}))
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
        endpoints = _endpoints_from_section_title(section.get("title", ""))
        if not endpoints:
            continue
        entry: dict[str, Any] = {}
        if cursor < len(tables):
            entry["request_parameters"] = _parameter_rows(tables[cursor])
            cursor += 1
        if cursor < len(tables):
            entry["response_parameters"] = _parameter_rows(tables[cursor])
            cursor += 1
        for endpoint in endpoints:
            by_endpoint[endpoint] = deepcopy(entry)
    return by_endpoint


def _endpoint_from_section_title(title: str) -> str:
    match = ENDPOINT_RE.search(title or "")
    return match.group(1) if match else ""


def _endpoints_from_section_title(title: str) -> list[str]:
    return _unique_matches(ENDPOINT_RE.findall(title or ""))


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


def _attach_endpoint_examples(
    endpoint: dict[str, Any],
    _error_codes: list[dict[str, str]],
    source_examples: dict[str, Any] | None = None,
) -> None:
    source_examples = source_examples or {}
    for key in ("request_example", "success_response_example", "error_response_example"):
        value = source_examples.get(key)
        if value:
            endpoint[key] = deepcopy(value)


def _endpoint_json_examples(sections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    examples: dict[str, dict[str, Any]] = {}
    for section in sections:
        title = section.get("title", "")
        content = [str(item) for item in section.get("content", [])]
        section_endpoints = _unique_matches(ENDPOINT_RE.findall(title + "\n" + "\n".join(content)))
        if not section_endpoints:
            continue

        current_endpoint = _endpoint_from_section_title(title) or section_endpoints[0]
        last_label_endpoint = ""
        example_mode = ""
        for block in content:
            block_mode = _content_example_mode(block)
            if block_mode:
                example_mode = block_mode

            parsed = _example_from_code_block(block)
            if parsed is None:
                endpoint_in_text = _endpoint_from_section_title(block)
                if endpoint_in_text:
                    current_endpoint = endpoint_in_text
                continue

            label = _code_block_label(block)
            labeled_endpoint = _endpoint_for_label(label, section_endpoints)
            if labeled_endpoint:
                current_endpoint = labeled_endpoint
                last_label_endpoint = labeled_endpoint

            target_endpoint = last_label_endpoint or current_endpoint
            if not target_endpoint:
                continue
            entry = examples.setdefault(target_endpoint, {})
            slot = _example_slot(label, example_mode, parsed)
            entry.setdefault(slot, parsed)
            if slot == "request_example":
                last_label_endpoint = target_endpoint
        _copy_examples_to_shared_section_endpoints(examples, section_endpoints)
    return examples


def _copy_examples_to_shared_section_endpoints(
    examples: dict[str, dict[str, Any]], section_endpoints: list[str]
) -> None:
    if len(section_endpoints) < 2:
        return
    source_endpoint = next(
        (endpoint for endpoint in section_endpoints if examples.get(endpoint)),
        "",
    )
    if not source_endpoint:
        return
    source_examples = examples.get(source_endpoint, {})
    for endpoint in section_endpoints:
        if endpoint == source_endpoint:
            continue
        entry = examples.setdefault(endpoint, {})
        for key, value in source_examples.items():
            entry.setdefault(key, deepcopy(value))


def _unique_matches(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value not in output:
            output.append(value)
    return output


def _example_from_code_block(block: str) -> Any | None:
    return _json_from_code_block(block) or _query_params_from_code_block(block)


def _json_from_code_block(block: str) -> Any | None:
    text = str(block or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    candidate = text[start:].strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _query_params_from_code_block(block: str) -> dict[str, Any] | None:
    text = str(block or "").strip()
    if not text:
        return None
    first_line = text.splitlines()[0].strip()
    if not first_line.startswith("?") and not urlsplit(first_line).query:
        return None
    query = urlsplit(first_line).query
    if not query:
        query = first_line[1:] if first_line.startswith("?") else ""
    if not query:
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return None
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key:
            output[key] = value
    return output or None


def _code_block_label(block: str) -> str:
    text = str(block or "").strip()
    start = text.find("{")
    return text[:start].strip().lower() if start > 0 else ""


def _content_example_mode(block: str) -> str:
    text = re.sub(r"\s+", " ", str(block or "").strip().lower())
    if text in {"request", "api request", "request body", "request example"}:
        return "request"
    if text in {"response", "api response", "response body", "response example"}:
        return "response"
    if text in {"error response", "api error response", "error response example"}:
        return "error_response"
    return ""


def _example_slot(label: str, example_mode: str, parsed: Any) -> str:
    normalized_label = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if "error" in normalized_label and "response" in normalized_label:
        return "error_response_example"
    if "request" in normalized_label:
        return "request_example"
    if "response" in normalized_label:
        return "success_response_example"
    if example_mode == "error_response":
        return "error_response_example"
    if example_mode == "request":
        return "request_example"
    if example_mode == "response":
        return "success_response_example"
    return "success_response_example" if _looks_like_response_example(parsed) else "request_example"


def _endpoint_for_label(label: str, endpoints: list[str]) -> str:
    normalized = re.sub(r"[^a-z0-9_/]+", " ", label.lower()).strip()
    if not normalized:
        return ""
    for endpoint in endpoints:
        endpoint_tail = endpoint.rstrip("/").rsplit("/", 1)[-1].lower()
        if normalized == endpoint_tail or endpoint_tail in normalized.split():
            return endpoint
    return ""


def _looks_like_response_example(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    response_keys = {"status", "data", "error", "result"}
    wallet_response_keys = {"balance", "currency", "denomination", "buffer"}
    request_keys = {"post_params", "retry", "game_result"}
    keys = set(value)
    return (
        bool(keys & response_keys) or wallet_response_keys.issubset(keys)
    ) and not bool(keys & request_keys)


def _extract_error_codes(parsed: dict[str, Any], text: str) -> list[dict[str, str]]:
    found: dict[str, str] = {}
    sections = _sections(parsed.get("paragraphs", []))
    for table in parsed.get("tables", []):
        if not table:
            continue
        headers = [_normalize_error_header(cell) for cell in table[0]]
        if "code" in headers and any(header in headers for header in ("message", "description", "context")):
            code_index = headers.index("code")
            message_index = _first_header_index(headers, ("message", "description", "context"))
            if message_index is None:
                continue
            exception_index = headers.index("related exceptions") if "related exceptions" in headers else None
            for row in table[1:]:
                if len(row) <= max(code_index, message_index):
                    continue
                code = row[code_index].strip()
                if not _is_error_code(code):
                    continue
                context = row[message_index].strip()
                if exception_index is not None and len(row) > exception_index and row[exception_index].strip():
                    context = f"{context} | {row[exception_index].strip()}"
                found.setdefault(code, context)

    for section in sections:
        title = section.get("title", "")
        content = section.get("content", [])
        if not _is_error_code_section(title, content):
            continue
        for code, context in _error_codes_from_section_content(content).items():
            found.setdefault(code, context)

    if found:
        return _sorted_error_codes(found)

    for match in ERROR_CODE_RE.finditer(text):
        code = match.group(1)
        if not _is_error_code(code):
            continue
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 180)
        found.setdefault(code, text[start:end].replace("\n", " ").strip())

    return _sorted_error_codes(found)


def _normalize_error_header(value: str) -> str:
    normalized = _normalize_header(value)
    aliases = {
        "error code": "code",
        "error codes": "code",
        "status code": "code",
        "response code": "code",
        "message": "message",
        "error message": "message",
        "description": "description",
        "desc": "description",
        "context": "context",
    }
    return aliases.get(normalized, normalized)


def _first_header_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for candidate in candidates:
        if candidate in headers:
            return headers.index(candidate)
    return None


def _is_error_code_section(title: str, content: list[str]) -> bool:
    title_text = _normalize_header(title)
    if "error code" in title_text or title_text == "errors":
        return True
    preview = " ".join(content[:8]).lower()
    return "error code" in preview and ("message" in preview or "description" in preview)


def _error_codes_from_section_content(content: list[str]) -> dict[str, str]:
    tokens = [str(item).strip() for item in content if str(item).strip()]
    found: dict[str, str] = {}
    start = _error_section_data_start(tokens)
    index = start
    while index < len(tokens):
        code = tokens[index].strip()
        if not _is_error_code(code):
            index += 1
            continue
        context_parts = []
        index += 1
        while index < len(tokens) and not _is_error_code(tokens[index]):
            token = tokens[index].strip()
            if token and _normalize_error_header(token) not in {"code", "message", "description", "context"}:
                context_parts.append(token)
            index += 1
        found.setdefault(code, " | ".join(context_parts).strip())
    return found


def _error_section_data_start(tokens: list[str]) -> int:
    for index, token in enumerate(tokens):
        if _is_error_code(token):
            return index
    return 0


def _is_error_code(value: str) -> bool:
    return bool(re.fullmatch(r"\d{1,6}", str(value).strip()))


def _sorted_error_codes(found: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"code": code, "context": context}
        for code, context in sorted(found.items(), key=lambda item: int(item[0]))
    ]


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
