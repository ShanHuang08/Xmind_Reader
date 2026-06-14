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
    checklist = _extract_vendor_master_checklist(parsed)
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
    return sorted(endpoints.values(), key=lambda item: item["endpoint"])


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
