"""Extract AI-friendly vendor API details from parsed documents."""

from __future__ import annotations

import re
import json
from collections import Counter
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from xml.etree import ElementTree

from doc_reader.parameter_dependency import compile_parameter_dependencies


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
    operation_variants = _endpoint_operation_variants(parsed)
    for endpoint, variants in _section_endpoint_operation_variants(parsed, sections).items():
        operation_variants.setdefault(endpoint, variants)
    error_codes = _extract_error_codes(parsed, text)
    dependency_profile, dependency_report = compile_parameter_dependencies(endpoints, error_codes)
    endpoint_examples = _endpoint_json_examples(sections, vendor_name)
    for endpoint in endpoints:
        _attach_operation_variants(
            endpoint,
            operation_variants.get(endpoint.get("endpoint", ""), []),
        )
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
        "parameter_dependencies": dependency_profile,
        "parameter_dependency_validation_report": dependency_report,
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
        title_endpoints = _endpoints_from_section_title(section.get("title", ""))
        section_endpoints = title_endpoints or _unique_matches(ENDPOINT_RE.findall(section_text))
        for endpoint in section_endpoints:
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
    for key in (
        "request_example",
        "success_response_example",
        "error_response_example",
        "additional_request_examples",
    ):
        value = source_examples.get(key)
        if value:
            endpoint[key] = deepcopy(value)


def _attach_operation_variants(
    endpoint: dict[str, Any], variants: list[dict[str, Any]]
) -> None:
    if not _requires_operation_variants(variants):
        return
    endpoint["operation_variants"] = variants


def _requires_operation_variants(variants: list[dict[str, Any]]) -> bool:
    if len(variants) > 1:
        return True
    if len(variants) != 1:
        return False
    return len(variants[0].get("request_examples", [])) > 1


def _endpoint_operation_variants(parsed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    paragraphs = parsed.get("paragraphs", [])
    parameter_tables = [
        table for table in parsed.get("tables", []) if _is_parameter_table(table)
    ]
    table_cursor = 0
    output: dict[str, list[dict[str, Any]]] = {}
    current: dict[str, Any] | None = None
    current_label = ""

    def flush() -> None:
        nonlocal current, table_cursor
        if not current:
            return
        request_parameters: list[dict[str, str]] = []
        response_parameters: list[dict[str, str]] = []
        if "request" in current.get("sections", {}) and table_cursor < len(parameter_tables):
            request_parameters = _parameter_rows(parameter_tables[table_cursor])
            table_cursor += 1
        if "response" in current.get("sections", {}) and table_cursor < len(parameter_tables):
            response_parameters = _parameter_rows(parameter_tables[table_cursor])
            table_cursor += 1
        variant = _operation_variant_from_block(
            current,
            request_parameters,
            response_parameters,
        )
        if variant:
            output.setdefault(variant["endpoint"], []).append(variant)
        current = None

    for paragraph in paragraphs:
        style = str(paragraph.get("style", "")).lower()
        text = str(paragraph.get("text", ""))
        if _is_endpoint_operation_heading(style, text):
            flush()
            current = {
                "title": text,
                "endpoint": _endpoint_from_section_title(text),
                "method": _method_from_heading(text),
                "operation": _operation_from_heading(text),
                "sections": {},
            }
            current_label = ""
            continue
        if not current:
            continue
        if style in {"h1", "h2", "h3"} or style.startswith("heading 3"):
            flush()
            current_label = ""
            continue
        if style in {"h4", "h5", "h6"} or style.startswith("heading 4"):
            current_label = text.strip().lower()
            current["sections"].setdefault(current_label, [])
            continue
        if current_label:
            current["sections"].setdefault(current_label, []).append(text)
    flush()
    return output


def _section_endpoint_operation_variants(
    parsed: dict[str, Any], sections: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Build variants for documents whose operations use regular H2 sections."""
    tables = [table for table in parsed.get("tables", []) if _is_parameter_table(table)]
    cursor = 0
    output: dict[str, list[dict[str, Any]]] = {}
    for section in sections:
        title = str(section.get("title", ""))
        endpoint = _endpoint_from_section_title(title)
        if not endpoint:
            continue
        request_parameters = _parameter_rows(tables[cursor]) if cursor < len(tables) else []
        cursor += 1
        response_parameters = _parameter_rows(tables[cursor]) if cursor < len(tables) else []
        cursor += 1

        request_examples: list[dict[str, Any]] = []
        success_examples: list[dict[str, Any]] = []
        error_examples: list[dict[str, Any]] = []
        for block in section.get("content", []):
            query = _query_params_from_code_block(str(block))
            if query:
                request_examples.append(query)
            for request, response in _xml_exchange_examples(str(block)):
                if request:
                    request_examples.append(request)
                if str(response.get("result", "")).upper() == "ERROR":
                    error_examples.append(response)
                elif response:
                    success_examples.append(response)

        variant = {
            "endpoint": endpoint,
            "method": _method_from_heading(title),
            "operation": _operation_from_heading(title),
            "title": title,
            "request_parameters": request_parameters,
            "response_parameters": response_parameters,
            "request_examples": _label_request_examples(request_examples),
            "success_response_examples": success_examples,
            "error_response_examples": error_examples,
        }
        if request_examples:
            variant["request_example"] = request_examples[0]
        if success_examples:
            variant["success_response_example"] = success_examples[0]
        if error_examples:
            variant["error_response_example"] = error_examples[0]
        output.setdefault(endpoint, []).append(
            {key: value for key, value in variant.items() if value not in ("", [], {})}
        )
    return output


def _is_endpoint_operation_heading(style: str, text: str) -> bool:
    return (
        (style in {"h3", "heading 3"} or style.startswith("heading 3"))
        and bool(_endpoint_from_section_title(text))
    )


def _operation_variant_from_block(
    block: dict[str, Any],
    request_parameters: list[dict[str, str]],
    response_parameters: list[dict[str, str]],
) -> dict[str, Any]:
    sections = block.get("sections", {})
    request_examples = _json_examples_from_sections(
        sections,
        labels=("example request", "request example"),
        response_mode=False,
    )
    success_examples = _json_examples_from_sections(
        sections,
        labels=("example response", "response example"),
        response_mode=True,
    )
    error_examples = _json_examples_from_sections(
        sections,
        labels=("example error response", "error response example"),
        response_mode=True,
    )
    variant = {
        "endpoint": block.get("endpoint", ""),
        "method": block.get("method", ""),
        "operation": block.get("operation", ""),
        "title": block.get("title", ""),
        "request_parameters": request_parameters,
        "response_parameters": response_parameters,
        "request_examples": _label_request_examples(request_examples),
        "success_response_examples": success_examples,
        "error_response_examples": error_examples,
    }
    if request_examples:
        variant["request_example"] = request_examples[0]
    if success_examples:
        variant["success_response_example"] = success_examples[0]
    if error_examples:
        variant["error_response_example"] = error_examples[0]
    return {key: value for key, value in variant.items() if value not in ("", [], {})}


def _json_examples_from_sections(
    sections: dict[str, list[str]],
    labels: tuple[str, ...],
    response_mode: bool,
) -> list[Any]:
    examples: list[Any] = []
    for label, content in sections.items():
        normalized = label.strip().lower()
        if normalized not in labels:
            continue
        for item in content:
            for parsed in _json_objects_from_text(item):
                if response_mode or not _looks_like_response_example(parsed):
                    examples.append(parsed)
    return examples


def _json_objects_from_text(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    source = str(text or "")
    objects: list[Any] = []
    index = 0
    while index < len(source):
        start = source.find("{", index)
        if start < 0:
            break
        try:
            parsed, end = decoder.raw_decode(source[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        objects.append(parsed)
        index = start + end
    return objects


def _label_request_examples(examples: list[Any]) -> list[dict[str, Any]]:
    labelled = []
    for example in examples:
        if isinstance(example, dict):
            labelled.append(
                {
                    "label": _request_example_label(example),
                    "example": example,
                }
            )
    return labelled


def _request_example_label(example: dict[str, Any]) -> str:
    parts = []
    for key in ("type", "promoType", "action", "operation"):
        value = example.get(key)
        if value not in (None, ""):
            parts.append(str(value))
    return " / ".join(parts) if parts else "request"


def _method_from_heading(text: str) -> str:
    match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\b", text, re.I)
    return match.group(1).upper() if match else ""


def _operation_from_heading(text: str) -> str:
    parenthetical = re.search(r"\(([^()]+)\)\s*$", text)
    if parenthetical:
        return parenthetical.group(1).strip()
    if "-" in text:
        return text.rsplit("-", 1)[-1].strip()
    return ""


def _endpoint_json_examples(sections: list[dict[str, Any]], vendor_name: str = "") -> dict[str, dict[str, Any]]:
    examples: dict[str, dict[str, Any]] = {}
    for section in sections:
        title = section.get("title", "")
        content = [str(item) for item in section.get("content", [])]
        title_endpoints = _endpoints_from_section_title(title)
        section_endpoints = title_endpoints or _unique_matches(ENDPOINT_RE.findall("\n".join(content)))
        if not section_endpoints:
            continue

        current_endpoint = _endpoint_from_section_title(title) or section_endpoints[0]
        last_label_endpoint = ""
        example_mode = ""
        example_label = ""
        for block in content:
            block_mode = _content_example_mode(block)
            if block_mode:
                example_mode = block_mode
                example_label = str(block)

            target_endpoint = last_label_endpoint or current_endpoint
            if target_endpoint:
                entry = examples.setdefault(target_endpoint, {})
                for request, response in _xml_exchange_examples(block):
                    if request:
                        _store_endpoint_example(
                            entry, "request_example", example_label, request, vendor_name
                        )
                    if str(response.get("result", "")).upper() == "ERROR":
                        _store_endpoint_example(
                            entry, "error_response_example", example_label, response, vendor_name
                        )
                    elif response:
                        _store_endpoint_example(
                            entry, "success_response_example", example_label, response, vendor_name
                        )

            parsed_examples = _examples_from_code_block(block)
            if not parsed_examples:
                endpoint_in_text = _endpoint_from_section_title(block)
                if endpoint_in_text:
                    current_endpoint = endpoint_in_text
                continue

            label = _code_block_label(block) or example_label
            labeled_endpoint = _endpoint_for_label(label, section_endpoints)
            if labeled_endpoint:
                current_endpoint = labeled_endpoint
                last_label_endpoint = labeled_endpoint

            target_endpoint = last_label_endpoint or current_endpoint
            if not target_endpoint:
                continue
            entry = examples.setdefault(target_endpoint, {})
            for parsed in parsed_examples:
                slot = _example_slot(label, example_mode, parsed)
                _store_endpoint_example(entry, slot, label, parsed, vendor_name)
                if slot == "request_example":
                    last_label_endpoint = target_endpoint
            example_label = ""
        _copy_examples_to_shared_section_endpoints(examples, section_endpoints)
    return examples


def _store_endpoint_example(
    entry: dict[str, Any], slot: str, label: str, parsed: Any, vendor_name: str = ""
) -> None:
    normalized_label = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if (
        _is_softgaming_vendor(vendor_name)
        and slot == "request_example"
        and _is_additional_request_label(normalized_label)
    ):
        examples = entry.setdefault("additional_request_examples", [])
        if isinstance(examples, list):
            examples.append({"label": str(label).strip(), "example": parsed})
        return
    if slot not in entry or _is_placeholder_example(entry.get(slot)):
        entry[slot] = parsed


def _is_additional_request_label(normalized_label: str) -> bool:
    return any(keyword in normalized_label for keyword in ("rollback", "cancel"))


def _is_softgaming_vendor(vendor_name: str) -> bool:
    return re.sub(r"[^a-z0-9]+", "", str(vendor_name).lower()) == "softgaming"


def _is_placeholder_example(value: Any) -> bool:
    return value in ({}, {"?": ""})


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
    examples = _examples_from_code_block(block)
    return examples[0] if examples else None


def _examples_from_code_block(block: str) -> list[Any]:
    json_examples = _json_examples_from_code_block(block)
    if json_examples:
        return json_examples
    query_params = _query_params_from_code_block(block)
    return [query_params] if query_params else []


def _json_examples_from_code_block(block: str) -> list[Any]:
    text = str(block or "").strip()
    # Documentation examples commonly contain JSON-style trailing commas.
    # Remove only commas immediately followed by a closing object/array token
    # so the complete example is parsed instead of a valid nested fragment.
    text = re.sub(r",(?=\s*[}\]])", "", text)
    start = text.find("{")
    if start < 0:
        return []
    decoder = json.JSONDecoder()
    examples = []
    index = start
    while index < len(text):
        brace_index = text.find("{", index)
        if brace_index < 0:
            break
        try:
            value, end = decoder.raw_decode(text[brace_index:])
        except json.JSONDecodeError:
            index = brace_index + 1
            continue
        examples.append(value)
        index = brace_index + end
    return examples


def _json_from_code_block(block: str) -> Any | None:
    examples = _json_examples_from_code_block(block)
    return examples[0] if examples else None


def _query_params_from_code_block(block: str) -> dict[str, Any] | None:
    text = str(block or "").strip()
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line = lines[0]
    split = urlsplit(first_line)
    if not first_line.startswith("?") and "?" not in first_line:
        return None
    query_parts = [split.query]
    for line in lines[1:]:
        continuation = line.lstrip("&?").strip()
        if re.match(r"^[^=&\s]+\s*=", continuation):
            query_parts.append(continuation)
    query = "&".join(part for part in query_parts if part)
    if not query:
        query = first_line[1:] if first_line.startswith("?") else ""
    if not query:
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return None
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key and key != "?":
            output[key] = value
    return output or None


def _xml_exchange_examples(block: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    exchanges: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for fragment in re.findall(r"<EXTSYSTEM\b[^>]*>.*?</EXTSYSTEM>", block, re.I | re.S):
        try:
            root = ElementTree.fromstring(fragment)
        except ElementTree.ParseError:
            continue
        request = _xml_children_dict(root.find("REQUEST"))
        response = _xml_children_dict(root.find("RESPONSE"))
        if request or response:
            exchanges.append((request, response))
    return exchanges


def _xml_children_dict(element: ElementTree.Element | None) -> dict[str, Any]:
    if element is None:
        return {}
    return {
        str(child.tag).lower(): (child.text or "").strip()
        for child in element
        if str(child.tag).strip()
    }


def _code_block_label(block: str) -> str:
    text = str(block or "").strip()
    start = text.find("{")
    return text[:start].strip().lower() if start > 0 else ""


def _content_example_mode(block: str) -> str:
    text = re.sub(r"\s+", " ", str(block or "").strip().lower())
    if (
        text in {"request", "api request", "request body"}
        or "request example" in text
        or ("example" in text and any(keyword in text for keyword in ("rollback", "cancel")))
    ):
        return "request"
    if "error response" in text:
        return "error_response"
    if text in {"response", "api response", "response body"} or "response example" in text:
        return "response"
    return ""


def _example_slot(label: str, example_mode: str, parsed: Any) -> str:
    normalized_label = re.sub(r"\s+", " ", str(label or "").strip().lower())
    if "error" in normalized_label and "response" in normalized_label:
        return "error_response_example"
    if "request" in normalized_label:
        return "request_example"
    if (
        isinstance(parsed, dict)
        and "error" in parsed
        and "request" not in normalized_label
    ):
        return "error_response_example"
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
                if not _is_error_code(code, mode="explicit_code_column"):
                    continue
                context = row[message_index].strip()
                if exception_index is not None and len(row) > exception_index and row[exception_index].strip():
                    context = f"{context} | {row[exception_index].strip()}"
                found.setdefault(code, context)
        elif "message" in headers and any(
            header in headers for header in ("related exception", "related exceptions", "description", "context")
        ):
            message_index = headers.index("message")
            context_index = _first_header_index(
                headers, ("related exception", "related exceptions", "description", "context")
            )
            for row in table[1:]:
                if len(row) <= message_index:
                    continue
                code = row[message_index].strip()
                if not _is_error_code(code, mode="message_as_code"):
                    continue
                context = ""
                if context_index is not None and len(row) > context_index:
                    context = row[context_index].strip()
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
        if not _is_error_code(code, mode="numeric_only"):
            continue
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 180)
        found.setdefault(code, text[start:end].replace("\n", " ").strip())

    return _sorted_error_codes(found)


def _normalize_error_header(value: str) -> str:
    normalized = _normalize_header(value)
    # Confluence exports may append a translated header in parentheses, for
    # example "Error ID (錯誤代碼)" or "Description (說明)".
    normalized = re.sub(r"\s*\([^)]*\)\s*", " ", normalized).strip()
    aliases = {
        "error code": "code",
        "error codes": "code",
        "error id": "code",
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
    mode = _error_section_code_mode(tokens)
    index = start
    while index < len(tokens):
        code = tokens[index].strip()
        if not _is_error_code(code, mode=mode):
            index += 1
            continue
        context_parts = []
        index += 1
        while index < len(tokens) and not _is_error_code(tokens[index], mode=mode):
            token = tokens[index].strip()
            if token and _normalize_error_header(token) not in {"code", "message", "description", "context"}:
                context_parts.append(token)
            index += 1
        found.setdefault(code, " | ".join(context_parts).strip())
    return found


def _error_section_data_start(tokens: list[str]) -> int:
    mode = _error_section_code_mode(tokens)
    for index, token in enumerate(tokens):
        if _is_error_code(token, mode=mode):
            return index
    return 0


def _error_section_code_mode(tokens: list[str]) -> str:
    normalized = [_normalize_error_header(token) for token in tokens[:8]]
    if "code" in normalized:
        return "explicit_code_column"
    if "message" in normalized and any(
        header in normalized for header in ("related exception", "related exceptions")
    ):
        return "message_as_code"
    return "numeric_only"


def _is_error_code(value: str, mode: str = "numeric_only") -> bool:
    text = str(value).strip()
    if re.fullmatch(r"\d{1,6}", text):
        return True
    if mode == "numeric_only":
        return False
    if not text or len(text) > 80:
        return False
    lowered = text.lower()
    if mode == "message_as_code":
        return any(term in lowered for term in ("error", "invalid", "failed", "expired", "funds", "signature"))
    if mode == "explicit_code_column":
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{2,}", text))
    return False


def _sorted_error_codes(found: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"code": code, "context": context}
        for code, context in sorted(found.items(), key=lambda item: _error_code_sort_key(item[0]))
    ]


def _error_code_sort_key(code: str) -> tuple[int, int | str]:
    text = str(code).strip()
    if text.isdigit():
        return (0, int(text))
    return (1, text.lower())


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
