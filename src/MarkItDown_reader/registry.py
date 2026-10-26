"""Small strategy registry; adding a normalizer never changes the Markdown reader."""
from __future__ import annotations

from typing import Callable
import re

from .contracts import digest, evidence, new_document, strict_json, json_text, document_status
from .source_chunker import chunk_source
from .api_scope import classify_and_select

OPENAPI_PREFIX = "<!-- openapi-source/v1 -->\n"
Strategy = Callable[[str, dict, list[dict]], dict]
STRATEGIES: dict[str, Strategy] = {}


def register(name: str, strategy: Strategy) -> None:
    if name in STRATEGIES:
        raise ValueError(f"Strategy already registered: {name}")
    STRATEGIES[name] = strategy


def operation(name, method, path, discriminator, ref, block_id):
    values = {"operation_name": name, "http_method": method, "url_or_path": path,
              "discriminator": discriminator, "role": None}
    return {"operation_id": "op_" + digest([method, path, discriminator, name])[:20],
            **values, "review_status": "rule_verified", "section_ids": [block_id],
            "evidence": {k: [ref] for k, v in values.items() if v is not None},
            "parameters": [], "examples": []}


def rules(source: str, meta: dict, blocks: list[dict]) -> dict:
    """Conservative block extraction. Never equate a match with full coverage."""
    doc = new_document(meta, source, blocks)
    lines = source.splitlines()
    # PDF-to-Markdown commonly flattens heading styles and splits URL / Method
    # across table rows. Split on numbered API headings first, then inspect the
    # complete operation section instead of looking for "POST /path" on one line.
    heading_re = re.compile(r"^\s*(\d+(?:\.\d+)+)\s+([A-Z][^\r\n]{1,100}?)\s*$")
    headings = []
    for i, line in enumerate(lines):
        match = heading_re.match(line)
        if match and not re.search(r"\.{3,}", line):
            headings.append((i, match.group(1), match.group(2).strip()))
    # Restrict candidates to numbered headings whose following content contains a URL/path.
    api_heads = [h for h in headings if re.search(r"\b(?:URL|Endpoint)\b|\{baseUri\}/|https?://|/api/", "\n".join(lines[h[0]:min(len(lines), h[0]+30)]), re.I)]
    # PDF converters often flatten heading styles. Recover the common
    # `Operation Name / Request: / POST: {base}/path` pattern without relying
    # on numbered headings or a single vendor's base-URL placeholder.
    if not api_heads:
        api_heads = _request_endpoint_heads(lines)
    spans = []
    for n, (start, number, title) in enumerate(api_heads):
        end = api_heads[n+1][0] if n+1 < len(api_heads) else len(lines)
        spans.append((start, end, number, title))
    if not spans:
        spans = [(b["line_start"]-1, b["line_end"], "", "") for b in blocks]

    seen = set()
    for block in blocks:
        if api_heads:
            # Numbered API manuals need section-local matching. The broad
            # fallback below otherwise mistakes prose and table fragments for
            # endpoint declarations.
            continue
        # Keep all source lines covered by the existing lossless section map.
        start, end = block["line_start"], block["line_end"]
        text = "\n".join(lines[start - 1:end])
        ref = evidence(source, start, end)
        # A label and its value may be separated by a newline; no document-wide guessing.
        matches = list(re.finditer(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s+(https?://[^\s|`]+|/[^\s|`]+)", text, re.I))
        pairs = [(m[1].upper(), m[2].rstrip(".,;")) for m in matches]
        if not pairs:
            paths = re.findall(r"\b(?:Path|Endpoint|URL)\s*[:：]\s*(https?://[^\s|`]+|/[^\s|`]+)", text, re.I)
            methods = set(x.upper() for x in re.findall(r"\b(?:HTTP\s+)?Method\s*:\s*(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\b", text, re.I))
            if len(set(paths)) == 1:
                pairs = [(next(iter(methods)) if len(methods) == 1 else None, paths[0])]
        # Action is a separate discriminator; its location remains unknown without evidence.
        actions = re.findall(r'\b(action|request)\s*[:=]\s*["\x27]?([\w-]+)', text, re.I)
        discriminator = ({"location": "unknown", "name": actions[0][0], "value": actions[0][1]}
                         if len(set(actions)) == 1 else None)
        if not pairs and discriminator:
            pairs = [(None, None)]
        for method, path in pairs:
            heading_name = re.findall(r"^#{1,6}\s+(.+)$", text, re.M)
            name = heading_name[0] if heading_name else (path or discriminator["value"])
            op = operation(name, method, path, discriminator, ref, block["block_id"])
            if op["operation_id"] in seen:
                continue
            seen.add(op["operation_id"])
            doc["operations"].append(op)

    # Section-aware extraction is useful for converter output where tables are
    # flattened. Evidence remains an exact quote from the converted Markdown.
    for sec_start, sec_end, number, title in spans:
        section = "\n".join(lines[sec_start:sec_end])
        path_match = re.search(r"(?:\{[A-Za-z_]\w*\})\s*(/[^\s|}`]+)|\b(?:URL|Endpoint)\s*[:|]?\s*(https?://[^\s|`]+|/[^\s|`]+)", section, re.I)
        path = ((path_match.group(1) or path_match.group(2)) if path_match else None)
        method_match = re.search(r"\b(?:HTTP\s+)?Method\b[\s\S]{0,100}?\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\b|\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s*:", section, re.I)
        method = next((group.upper() for group in method_match.groups() if group), None) if method_match else None
        if not path:
            continue
        absolute_start, absolute_end = sec_start + 1, sec_end
        section_ref = evidence(source, absolute_start, absolute_end)
        name = title or path.rstrip("/").split("/")[-1].replace("-", " ").title()
        block_id = next((b["block_id"] for b in blocks if b["line_start"] <= absolute_start <= b["line_end"]), blocks[0]["block_id"])
        action_match = re.search(r"(?:[\"'](?P<key>action|request|operation|transactionType)[\"']|(?P<bare>action|operation|transactionType))[ \t]*[:=][ \t]*[\"']?(?P<value>[\w-]+)", section, re.I)
        discriminator = ({"location": "unknown", "name": action_match.group("key") or action_match.group("bare"), "value": action_match.group("value")}
                         if action_match else None)
        op = operation(name, method, path, discriminator, section_ref, block_id)
        op["evidence"] = {}
        name_line = next((i for i in range(sec_start, sec_end) if lines[i].strip() == f"{number} {title}"), sec_start)
        if name:
            op["evidence"]["operation_name"] = [evidence(source, name_line + 1, name_line + 1)]
        if method and method_match:
            method_group = next(i for i, group in enumerate(method_match.groups(), 1) if group)
            method_line = sec_start + section[:method_match.start(method_group)].count("\n")
            op["evidence"]["http_method"] = [evidence(source, method_line + 1, method_line + 1)]
        if path and path_match:
            path_group = next(i for i, group in enumerate(path_match.groups(), 1) if group)
            path_line = sec_start + section[:path_match.start(path_group)].count("\n")
            op["evidence"]["url_or_path"] = [evidence(source, path_line + 1, path_line + 1)]
        if discriminator and action_match:
            action_line = sec_start + section[:action_match.start()].count("\n")
            op["evidence"]["discriminator"] = [evidence(source, action_line + 1, action_line + 1)]
        op["source_section"] = {"number": number, "title": title, "line_start": absolute_start, "line_end": absolute_end}
        op["logic"] = section.strip()
        op["source_description"] = _section_description(section, title)
        # Parse request and response body templates separately. A single
        # document-wide key scan incorrectly classified response fields (e.g.
        # statusCode) as request parameters.
        request_body = re.search(r"Request\s+Body\b(.*?)(?:Response\s+Body\b|\n\s*Request\s*:|\Z)", section, re.I | re.S)
        response_body = re.search(r"Response\s+Body\b(.*?)(?:\n\s*Request\s*:|\n\s*Possible Status|\Z)", section, re.I | re.S)
        body_fields = {
            "request": _body_field_names(request_body.group(1) if request_body else ""),
            "response": _body_field_names(response_body.group(1) if response_body else ""),
        }
        parameter_areas = _parameter_areas(section)
        for kind, area_start, area_end in parameter_areas:
            table_offset = sec_start + section[:area_start].count("\n")
            table_parameters = _parse_parameter_rows(section[area_start:area_end], kind, source,
                                                     table_offset, body_fields[kind])
            op["parameters"].extend(table_parameters)
            existing = {p.get("name") for p in op["parameters"] if p.get("direction") == kind}
            for field in body_fields[kind]:
                if field in existing:
                    continue
                body_text = (request_body if kind == "request" else response_body)
                region = body_text.group(1) if body_text else ""
                pos = re.search(rf"[\"']{re.escape(field)}[\"']\s*:", region)
                param_line = (sec_start + section[:body_text.start(1)].count("\n") + region[:pos.start()].count("\n")) if pos and body_text else sec_start
                parameter = {"name": field, "type": None, "required": None, "description": "",
                             "direction": kind, "required_basis": "not specified in source"}
                op["parameters"].append({"name": field, "direction": kind, "raw": json_text(parameter),
                    "evidence": evidence(source, param_line + 1, param_line + 1)})
        _normalize_nested_dto_parameters(op, section, source, sec_start)
        # Capture JSON object examples following explicit Request/Response labels.
        # "Response Example:" is a container label; the following block is
        # explicitly labelled Request, OK Response, or Error Response. Do not
        # attach the first following JSON object to that container label.
        for marker in re.finditer(r"(?im)^\s*(Request|OK Response|Error Response)\s*:?\s*$", section):
            tail = section[marker.end():]
            opening = tail.find("{")
            if opening < 0 or opening > 100 or "|" in tail[:opening] or "<" in tail[opening:tail.find("}", opening) if "}" in tail[opening:] else len(tail)]:
                continue
            raw = _balanced_json_object(tail[opening:])
            if raw:
                position = section.find(raw, marker.end())
                first_line = sec_start + section[:position].count("\n") + 1
                last_line = first_line + raw.count("\n")
                op["examples"].append({"kind": marker.group(1).strip().lower().replace(" ", "_"), "raw": raw,
                    "evidence": evidence(source, first_line, last_line)})
        # Preserve status-code tokens and operational prose without guessing semantics.
        codes = list(dict.fromkeys(re.findall(r"\b(?:OK|ERR_[A-Z0-9_]+)\b", section)))
        op["status_codes"] = codes
        op["review_status"] = "rule_verified" if method and path else "pending"
        for match in re.finditer(r"\b(ERR_[A-Z0-9_]+)\b([^\r\n]*(?:\r?\n(?!\s*ERR_)[^\r\n]+){0,2})", section):
            code = match.group(1)
            context = re.sub(r"\s+", " ", match.group(2)).strip(" .:-")
            row = {"code": code, "context": context or "Context retained in endpoint source section.",
                   "scope": op["operation_id"], "review_status": "pending", "response_json": None,
                   "evidence": evidence(source, sec_start + section[:match.start(1)].count("\n") + 1,
                                         sec_start + section[:match.start(1)].count("\n") + 1)}
            if not any(x["code"] == code and x["scope"] == op["operation_id"] for x in doc["error_codes"]):
                doc["error_codes"].append(row)
        existing = next((x for x in doc["operations"] if x["operation_id"] == op["operation_id"]), None)
        if existing:
            existing.update(op)
        else:
            doc["operations"].append(op)

    _extract_numeric_error_codes(doc, source)

    # Avoid silently declaring a document complete when extraction found only
    # partial API coverage; the raw text remains available for review.
    if doc["operations"]:
        mapped = {sid for op in doc["operations"] for sid in op["section_ids"]}
        for item in doc["coverage"]:
            if item["block_id"] in mapped:
                item.update(state="mapped", reason="Contains extracted API operation(s)")
    # All source remains visible. Human review can resolve coverage without changing code.
    doc["status"] = document_status(doc)
    return doc


def _balanced_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    quoted = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def _request_endpoint_heads(lines: list[str]) -> list[tuple[int, str, str]]:
    """Find plain-text API titles followed by an explicit method and URL."""
    heads = []
    path_re = re.compile(r"\{[A-Za-z_]\w*\}\s*/[^\s|}`]+|https?://[^\s|`]+|/(?:api|wallet|game)[^\s|}`]*", re.I)
    method_re = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s*:", re.I)
    for request_line, line in enumerate(lines):
        if line.strip().rstrip(":").casefold() != "request":
            continue
        nearby = "\n".join(lines[request_line + 1:min(len(lines), request_line + 8)])
        if not path_re.search(nearby) or not method_re.search(nearby):
            continue
        for title_line in range(request_line - 1, max(-1, request_line - 12), -1):
            candidate = lines[title_line].strip().strip("* ")
            if not candidate or candidate.casefold().rstrip(":") == "request":
                continue
            # Ignore page-numbered PDF example lines, table fragments, and prose.
            candidate = re.sub(r"^\d+\s+", "", candidate).strip()
            if (len(candidate) <= 80 and re.fullmatch(r"[A-Za-z][A-Za-z0-9 _/-]*", candidate)
                    and not candidate.casefold().startswith(("response", "request", "description", "example"))):
                heads.append((title_line, "", candidate))
                break
    # Preserve document order and remove duplicate headings found by repeated request snippets.
    result = []
    seen = set()
    for head in heads:
        if head[0] not in seen:
            seen.add(head[0]); result.append(head)
    return sorted(result)


def _parameter_areas(section: str) -> list[tuple[str, int, int]]:
    """Locate request/response field tables, skipping endpoint declaration labels."""
    headings = []
    pattern = re.compile(r"(?im)^\s*(Request(?:\s+data)?|Response(?:\s+data)?)\s*:?\s*$")
    for match in pattern.finditer(section):
        kind = "request" if match.group(1).lower().startswith("request") else "response"
        following = section[match.end():match.end() + 240]
        # The first Request: in many manuals introduces METHOD + URL, not fields.
        if kind == "request" and re.search(
                r"(?is)^\s*(?:(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s*:|\{[A-Za-z_]\w*\}\s*/)",
                following):
            continue
        headings.append((kind, match.start(), match.end()))
    result = []
    for index, (kind, _, content_start) in enumerate(headings):
        content_end = headings[index + 1][1] if index + 1 < len(headings) else len(section)
        stop = re.search(r"(?im)^\s*(?:Example\s*:|Request\s+body\s+example\b|Response\s+json\s*:|Possible Status\b)",
                         section[content_start:content_end])
        if stop:
            content_end = content_start + stop.start()
        if content_start < content_end:
            result.append((kind, content_start, content_end))
    return result


def _normalize_nested_dto_parameters(op: dict, section: str, source: str, section_start: int) -> None:
    """Represent nested request/response DTOs as JSON objects and scope child keys."""
    dto_headers = {
        "BetRequest": ("request", "bet"), "ResultRequest": ("request", "win"),
        "BetResponse": ("response", "bet"), "ResultResponse": ("response", "win"),
    }
    headings = []
    for offset, line in enumerate(section.splitlines()):
        item = dto_headers.get(line.strip())
        if item:
            headings.append((section_start + offset + 1, *item))

    for parameter in op.get("parameters", []):
        try:
            record = strict_json(parameter.get("raw", "{}"))
        except ValueError:
            continue
        name = parameter.get("name", "")
        direction = parameter.get("direction")
        source_type = record.get("type")
        is_custom_type = (isinstance(source_type, str) and
                          source_type.casefold() not in _PARAM_TYPES and
                          bool(re.fullmatch(r"[A-Z][A-Za-z0-9_.]*(?:<[^>]+>)?", source_type)))
        if is_custom_type:
            record["schema_name"] = source_type
            record["type"] = "object"

        evidence_ref = parameter.get("evidence", {})
        line_start = evidence_ref.get("line_start", 0) if isinstance(evidence_ref, dict) else 0
        active = next((entry for entry in reversed(headings)
                       if entry[0] <= line_start and entry[1] == direction), None)
        if active and not is_custom_type:
            parent = active[2]
            parameter["name"] = f"{parent}.{name}"
            record["name"] = parameter["name"]
        parameter["raw"] = json_text(record)


def _extract_numeric_error_codes(doc: dict, source: str) -> None:
    """Extract numbered codes only from explicitly titled code-list sections."""
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines)
              if re.search(r"\b(?:error\s+codes?|list\s+of\s+codes)\b", line, re.I)]
    row_re = re.compile(r"^\s*\|\s*(\d+)\s+([^|]+?)\s*\|", re.I)
    seen = {(item.get("code"), item.get("scope")) for item in doc["error_codes"]}
    for start in starts:
        stop = min(len(lines), start + 120)
        rows = []
        for index in range(start + 1, stop):
            match = row_re.match(lines[index])
            if match:
                rows.append((index, match.group(1), match.group(2).strip()))
        for row_index, code, description in rows:
            key = (code, "document")
            if key in seen:
                continue
            next_row = next((index for index, _, _ in rows if index > row_index), stop)
            continuation = []
            last_line = row_index
            for index in range(row_index + 1, next_row):
                value = lines[index].strip()
                if not value or re.fullmatch(r"[|\-: ]+", value) or "|" in value:
                    continue
                if re.search(r"\b(?:request|response|example|error\s+codes?)\b", value, re.I):
                    break
                continuation.append(value)
                last_line = index
            context = " ".join([description, *continuation]).strip()
            doc["error_codes"].append({"code": code, "context": context or "Document code entry.",
                "scope": "document", "review_status": "pending", "response_json": None,
                "evidence": evidence(source, row_index + 1, last_line + 1)})
            seen.add(key)


def _section_description(section: str, title: str) -> str:
    lines = section.splitlines()
    if lines and re.sub(r"^\s*\d+(?:\.\d+)+\s*", "", lines[0]).strip().casefold() == title.casefold():
        lines = lines[1:]
    description = []
    for line in lines:
        value = line.strip()
        if not value:
            if description:
                break
            continue
        if (re.search(r"\b(?:URL|Endpoint|Method|Headers?|Request Body|Response Body)\b", value, re.I)
                or value.startswith("|") or value.startswith("{") or value.startswith("}")):
            break
        description.append(value)
    return " ".join(description)


_PARAM_TYPES = {"string", "number", "integer", "int", "long", "float", "double",
                "boolean", "bool", "decimal", "object", "array", "date", "datetime", "uuid", "enum"}


def _body_field_names(text: str) -> list[str]:
    """Return property names from one request/response template only."""
    return list(dict.fromkeys(re.findall(r"(?m)^\s*[\"'“”‘’]?([A-Za-z_][\w.]*)[\"'“”‘’]?\s*:\s*<", text)))


def _parse_parameter_rows(text: str, direction: str, source: str, absolute_line_offset: int,
                          known_fields: list[str] | None = None) -> list[dict]:
    """Recover parameter rows even when PDF conversion split descriptions across lines."""
    parsed: list[dict] = []
    pending: list[tuple[int, str]] = []
    current: dict | None = None

    def append_to_current(fragments: list[tuple[int, str]]):
        if not current or not fragments:
            return
        for fragment_line, fragment in fragments:
            continuation = fragment.strip()
            if not continuation:
                continue
            # PDF tables sometimes put a type on a separate continuation line
            # (e.g. `giftSpin | | N` followed by `object ...`).
            match = re.match(r"^(string|number|integer|int|long|float|double|boolean|bool|decimal|object|array|date|datetime)\b[,:; ]*(.*)$", continuation, re.I)
            if not current["type"] and match:
                current["type"] = match.group(1).lower()
                continuation = match.group(2).strip()
            if continuation:
                current["description"] = " ".join(x for x in (current["description"], continuation) if x).strip()
            end_line = absolute_line_offset + fragment_line + 1
            current["evidence"] = evidence(source, current["line_start"], max(current["line_end"], end_line))

    for line_number, line in enumerate(text.splitlines()):
        row = _parameter_row(line)
        if row is None and "|" in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            pending_text = " ".join(value for _, value in pending)
            inferred_name = next((field for field in (known_fields or [])
                                  if re.search(rf"(?<![\w.]){re.escape(field)}(?![\w.])", pending_text, re.I)), None)
            if inferred_name and (not cells[0] or not re.fullmatch(r"[A-Za-z_][\w.]*(?:\[\])?", cells[0])):
                type_name = next((cell.lower() for cell in cells if cell.lower() in _PARAM_TYPES), None)
                required_cell = next((cell for cell in cells if re.match(r"^[YN](?:\s|$)", cell, re.I)), None)
                if type_name or required_cell:
                    req_index = cells.index(required_cell) if required_cell else -1
                    description = " ".join(x for x in ([required_cell[1:].strip()] if required_cell else []) + cells[req_index+1:] if x).strip()
                    row = (inferred_name, type_name, required_cell[0].upper() == "Y" if required_cell else None, description)
        if row:
            name, type_name, required, description = row
            prefix_lines, continuation_lines = [], []
            prefix_group = False
            for fragment_line, fragment in pending:
                if re.fullmatch(re.escape(name), fragment.strip(), re.I):
                    prefix_group = True  # bare field-name line before its broken table row
                elif _description_for_next(fragment, current, name, type_name):
                    prefix_group = True
                if prefix_group:
                    prefix_lines.append((fragment_line, fragment))
                else:
                    continuation_lines.append((fragment_line, fragment))
            append_to_current(continuation_lines)
            prefix = " ".join(value.strip() for _, value in prefix_lines
                               if value.strip() and not re.fullmatch(re.escape(name), value.strip(), re.I))
            prefix_start = prefix_lines[0][0] if prefix_lines else line_number
            pending = []
            if prefix:
                description = " ".join(x for x in (prefix, description) if x).strip()
            source_line = absolute_line_offset + line_number + 1
            current = {"name": name, "type": type_name, "required": required,
                       "description": description, "direction": direction,
                       "line_start": absolute_line_offset + prefix_start + 1,
                       "line_end": source_line,
                       "evidence": evidence(source, absolute_line_offset + prefix_start + 1, source_line)}
            parsed.append(current)
            continue

        stripped = line.strip()
        if not stripped or _parameter_table_decoration(stripped):
            continue
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*(?:Request|Response|Dto|Model)", stripped):
            # Nested DTO section labels (BetRequest, ResultResponse, ...) are
            # schema headings, not description fragments for the next row.
            continue
        if not re.match(r"^(?:parameter|parameters|values|mandatory|required|description|request|response)\b", stripped, re.I):
            pending.append((line_number, stripped))

    append_to_current(pending)
    result = []
    for parameter in parsed:
        required = parameter["required"]
        record = {k: parameter[k] for k in ("name", "type", "description", "direction")}
        record["required"] = required
        if required is None:
            record["required_basis"] = "not specified in source"
        result.append({"name": parameter["name"], "direction": direction,
                       "raw": json_text(record), "evidence": parameter["evidence"]})
    return result


def _description_for_next(fragment: str, current: dict | None, next_name: str, next_type: str | None) -> bool:
    text = fragment.lower().strip()
    if current is None:
        return True
    if re.fullmatch(re.escape(next_name), text, re.I):
        return True
    if not text:
        return False
    # A following type-only row belongs to the preceding parameter.
    if current.get("type") is None and re.match(r"^(string|number|integer|int|long|float|double|boolean|bool|decimal|object|array|date|datetime)\b", text):
        return False
    if next_type == "boolean" and re.search(r"\b(specify|indicate|whether|if this is|if the)\b", text):
        return True
    if re.match(r"^(object|array)\s+containing\b", text) and (next_type in {None, "object", "array"} or next_name.lower() in text):
        return True
    if re.match(r"^\(?optional\)?\s+predicted jackpot deduction\b", text) and next_name.lower() == "deduction":
        return True
    if re.match(r"^(?:secure code|currency code|unique game identifier|jackpot deduction|transfer reason|array containing|unique (?:identifier|reference)|field indicating|indication|player balance|jackpot (?:type|name|level)|jackpot unique identifier)\b", text):
        aliases = {
            "playerid": ("player", "operator's"), "sessionid": ("session",),
            "defencecode": ("secure code", "defence code", "defense code", "token"),
            "defensecode": ("secure code", "defence code", "defense code", "token"),
            "roundcompleted": ("last transaction", "round"), "currency": ("currency",),
            "gamekey": ("unique game identifier", "game key", "game identifier"),
            "giftspin": ("object containing", "campaign"), "jackpotwins": ("array containing", "jackpot wins"),
            "jackpotwins.type": ("jackpot type",), "jackpotwins.jackpotname": ("jackpot name",),
            "jackpotwins.levelname": ("jackpot level",), "jackpotwins.winid": ("unique identifier",),
            "deduction": ("jackpot deduction",), "balance": ("player balance",),
            "casinotransferid": ("unique reference", "transfer"), "bonusamount": ("bonus", "field indicating"),
            "realamount": ("real money", "indication"), "amount": ("transfer amount",),
            "reason": ("transfer reason",),
        }
        if any(alias in text for alias in aliases.get(next_name.lower(), ())):
            return True
    # Lowercase fragments usually continue the preceding sentence (PDF line wrap).
    if text[0].islower() or text.startswith(("(", "-", "“", '"')):
        return False
    return False


def _parameter_row(line: str) -> tuple[str, str | None, bool | None, str] | None:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")] if "|" in line else []
    name = type_name = None
    required = None
    description = ""
    if cells:
        if not re.fullmatch(r"[A-Za-z_][\w.]*(?:\[\])?", cells[0]):
            return None
        name = cells[0]
        type_index = next((i for i, cell in enumerate(cells[1:], 1) if cell.lower() in _PARAM_TYPES), None)
        if type_index is None:
            type_index = next((i for i, cell in enumerate(cells[1:], 1)
                               if re.fullmatch(r"[A-Z][A-Za-z0-9_.]*(?:<[^>]+>)?", cell)), None)
        req_index = next((i for i, cell in enumerate(cells[1:], 1) if re.match(r"^[YN](?:\s|$)", cell, re.I)), None)
        if type_index is not None:
            type_name = cells[type_index] if type_index > 0 and cells[type_index] not in _PARAM_TYPES else cells[type_index].lower()
        if req_index is not None:
            required = cells[req_index][0].upper() == "Y"
            description_parts = [cells[req_index][1:].strip(), *cells[req_index+1:]]
            description = " ".join(x for x in description_parts if x).strip()
        elif type_index is not None:
            description = " ".join(cells[type_index+1:]).strip()
    else:
        match = re.match(r"^\s*([A-Za-z_][\w.]*)\s+(string|number|integer|int|long|float|double|boolean|bool|decimal|object|array|date|datetime)(?:\s+([YN])\b)?\s*(.*?)\s*$", line, re.I)
        if match:
            name, type_name, flag, description = match.groups()
            type_name = type_name.lower()
            required = flag.upper() == "Y" if flag else None
        else:
            return None
    if not name or name.lower() in {"parameter", "parameters", "values", "mandatory", "required", "description"}:
        return None
    return name, type_name, required, description


def _parameter_table_decoration(line: str) -> bool:
    if re.fullmatch(r"[|\-: ]+", line):
        return True
    if line.startswith("|") and re.search(r"parameter|values|mandatory|required|description", line, re.I):
        return True
    if re.match(r"^(?:API Specification|Copyright|Possible Status|Status codes|Example|Response Example)\b", line, re.I):
        return True
    return False


def openapi(source: str, meta: dict, blocks: list[dict]) -> dict:
    payload = strict_json(source[len(OPENAPI_PREFIX):])
    doc = new_document(meta, source, blocks)
    doc["strategy"] = {"id": "openapi", "version": "1"}
    ref = evidence(source, 1, len(source.splitlines()))
    for path, methods in payload.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, item in methods.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"} or not isinstance(item, dict):
                continue
            op = operation(item.get("summary") or item.get("operationId") or path,
                           method.upper(), path, None, ref, blocks[0]["block_id"])
            for param in methods.get("parameters", []) + item.get("parameters", []):
                op["parameters"].append({"raw": json_text(param), "evidence": ref})
            for key in ("requestBody", "responses"):
                if key in item:
                    op["examples"].append({"raw": json_text(item[key]), "kind": key, "evidence": ref})
            doc["operations"].append(op)
    # Keep coverage pending: refs, security definitions, and business semantics require review.
    return doc


register("rules", rules)
register("openapi", openapi)


def normalize(source: str, meta: dict, strategy_id: str | None = None) -> dict:
    strategy_id = strategy_id or ("openapi" if source.startswith(OPENAPI_PREFIX) else "rules")
    if strategy_id not in STRATEGIES:
        raise ValueError(f"Unsupported normalization strategy: {strategy_id}")
    doc = STRATEGIES[strategy_id](source, meta, chunk_source(source))
    return classify_and_select(doc)
