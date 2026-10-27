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
        path_match = re.search(r"(?:\{[A-Za-z_]\w*\})\s*(/[^\s|`]+)|\b(?:URL|Endpoint)\s*[:|]?\s*(https?://[^\s|`]+|/[^\s|`]+)", section, re.I)
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

    _extract_callback_heading_operations(doc, source, lines, blocks)
    _extract_documented_url_operations(doc, source, lines, blocks)
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


_HTTP_URL_RE = re.compile(r"https?://[^\s|`]+", re.I)
_DO_PATH_RE = re.compile(r"(?<![\w./-])(?:[A-Za-z][A-Za-z0-9_-]*\.do)(?![\w.-])", re.I)


def _extract_documented_url_operations(doc: dict, source: str, lines: list[str], blocks: list[dict]) -> None:
    """Recover endpoints documented as request examples or prose.

    PDF converters often leave a URL on its own line, without the HTTP method
    and without a Markdown link.  Keep this generic: only `.do` endpoints
    which occur in an API/request/example context are promoted, while the
    normal scope classifier decides whether a game-wallet operation is useful.
    """
    candidates: dict[str, dict] = {}
    for index, line in enumerate(lines):
        urls = _HTTP_URL_RE.findall(line)
        paths = _DO_PATH_RE.findall(line)
        if not urls and not paths:
            continue
        context = " ".join(lines[max(0, index - 2):min(len(lines), index + 3)])
        if not urls and not re.search(r"\b(?:request|response|example|api|authenticate|bet|refund|result)\b", context, re.I):
            continue
        for value in urls:
            match = re.search(r"/([A-Za-z][A-Za-z0-9_-]*\.do)", value, re.I)
            if not match:
                continue
            path = "/" + match.group(1)
            key = path.lstrip("/").casefold()
            candidate = candidates.setdefault(key, {"path": path, "lines": [], "url_lines": []})
            candidate["lines"].append(index)
            candidate["url_lines"].append(index)
        for value in paths:
            # In prose (e.g. ``refundBet.do API requests``) there is no
            # leading slash to cite. Preserve the documented spelling so the
            # evidence contract remains exact; URL examples are handled above
            # and retain their `/endpoint.do` path.
            path = value if "/" not in line[:line.casefold().find(value.casefold())] else "/" + value
            key = path.lstrip("/").casefold()
            candidates.setdefault(key, {"path": path, "lines": [], "url_lines": []})["lines"].append(index)

    existing = {str(op.get("url_or_path", "")).split("?")[0].lstrip("/").casefold() for op in doc["operations"]}
    for candidate in candidates.values():
        path = candidate["path"]
        if path.lstrip("/").casefold() in existing:
            continue
        # Mentions in explanatory prose are useful for classification, but
        # parameter tables/examples belong to the endpoint's document section.
        occurrence_lines = sorted(set(candidate["url_lines"] or candidate["lines"]))
        name = _documented_endpoint_name(path, lines, occurrence_lines)
        context_start, context_end, relevant_occurrences = _endpoint_context_bounds(
            lines, path, occurrence_lines
        )
        block = next((item for item in blocks if item["line_start"] <= context_start + 1 <= item["line_end"]), blocks[0])
        ref = evidence(source, occurrence_lines[0] + 1, occurrence_lines[0] + 1)
        method, method_line = _documented_http_method(lines, occurrence_lines)
        op = operation(name, method, path, None, ref, block["block_id"])
        op["evidence"]["operation_name"] = [ref]
        op["evidence"]["url_or_path"] = [ref]
        if method_line is not None:
            op["evidence"]["http_method"] = [evidence(source, method_line + 1, method_line + 1)]
        # Combine the local request examples and parameter pages for this
        # endpoint. This preserves enough context for balance/result semantics
        # and lets the existing parameter parser build request/response rows.
        context_lines = list(range(context_start, context_end))
        context = "\n".join(lines[i] for i in context_lines)
        op["logic"] = context
        op["source_description"] = _section_description(context, name)
        for kind, area_start, area_end in _parameter_areas(context):
            offset = context[:area_start].count("\n")
            op["parameters"].extend(_parse_parameter_rows(
                context[area_start:area_end], kind, source, context_lines[offset]
            ))
        _append_documented_examples(op, source, lines, relevant_occurrences,
                                     context_start, context_end)
        op["source_section"] = {"number": "", "title": name,
                                 "line_start": context_start + 1,
                                 "line_end": context_end}
        op["review_status"] = "pending"
        doc["operations"].append(op)
        existing.add(path.lstrip("/").casefold())

    # A URL may already have been extracted by the older method/path rule. If
    # its method was missing, apply the same explicit protocol evidence to it.
    for op in doc["operations"]:
        if op.get("http_method") or not op.get("url_or_path"):
            continue
        basename_match = re.search(r"([A-Za-z][A-Za-z0-9_-]*\.do)", str(op["url_or_path"]), re.I)
        if not basename_match:
            continue
        basename = basename_match.group(1).casefold()
        occurrences = [index for index, line in enumerate(lines) if basename in line.casefold()]
        method, method_line = _documented_http_method(lines, occurrences)
        if method is None or method_line is None:
            continue
        op["http_method"] = method
        op.setdefault("evidence", {})["http_method"] = [evidence(source, method_line + 1, method_line + 1)]


def _endpoint_context_bounds(lines: list[str], path: str, occurrence_lines: list[int]) -> tuple[int, int, list[int]]:
    """Select one endpoint section instead of merging nearby API pages."""
    basename = str(path).rsplit("/", 1)[-1].split("?", 1)[0].casefold().removesuffix(".do")
    semantic = {
        "authenticate": r"token\s+authentication|authentication\s+request",
        "betresult": r"bet\s*/\s*result|bet\s+and\s+win",
        "refundbet": r"\brefund\b",
    }.get(basename)
    # The last request URL for an endpoint is normally inside its detailed
    # API section. Start from that occurrence so preceding shared protocol
    # examples do not contaminate the parameter table.
    anchor = max(occurrence_lines)
    # Bound the section at the next numbered API heading or obvious endpoint
    # section heading. This keeps Bet/Result data away from Refund data.
    start = anchor
    for index in range(anchor, -1, -1):
        heading = lines[index].lstrip("\f")
        if re.match(r"^\s*(?:\d+(?:\.\d+)+\.?\s+|Game Provider Response:)", heading, re.I):
            start = index
            break
    end = len(lines)
    for index in range(start + 1, len(lines)):
        heading = lines[index].lstrip("\f")
        if re.match(r"^\s*(?:\d+(?:\.\d+)+\.?\s+|V\.\s+|VI\.\s+)", heading, re.I):
            if index > anchor:
                end = index
                break
    relevant = [index for index in occurrence_lines if start <= index < end]
    if not relevant:
        relevant = [max(start, min(anchor, end - 1))]
    return start, end, relevant

def _documented_http_method(lines: list[str], occurrence_lines: list[int]) -> tuple[str | None, int | None]:
    """Infer method only from explicit document wording.

    MegaFair documents callbacks as supporting ``GET/POST method``.  For the
    wallet integration, POST is the safer documented choice when both are
    listed; a standalone GET remains GET. Never invent a method otherwise.
    """
    nearby_indexes = {
        index for occurrence in occurrence_lines
        for index in range(max(0, occurrence - 15), min(len(lines), occurrence + 16))
    }
    generic = re.compile(r"\bGET\s*/\s*POST\b|\bPOST\s*/\s*GET\b|\bGET\s+or\s+POST\b", re.I)
    explicit = re.compile(r"\b(?:HTTP\s+Request\s+method\s*:\s*|HTTP\s+method\s*:\s*|)\s*(GET|POST)\b", re.I)
    for index in sorted(nearby_indexes):
        line = lines[index]
        if generic.search(line):
            return "POST", index
        match = explicit.search(line)
        if match:
            return match.group(1).upper(), index
    # A manual may state the callback protocol once in a shared section and
    # omit the method again beside each individual callback URL.
    for index, line in enumerate(lines):
        if generic.search(line):
            return "POST", index
    return None, None


def _documented_endpoint_name(path: str, lines: list[str], occurrence_lines: list[int]) -> str:
    basename = path.rsplit("/", 1)[-1].removesuffix(".do")
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", basename).replace("_", " ").replace("-", " ")
    if basename.casefold() == "betresult":
        return "Bet/Result"
    if basename.casefold() == "refundbet":
        return "Refund"
    if basename.casefold() == "authenticate":
        return "Authenticate"
    return normalized.title()


_VERTICAL_FIELD_NAMES = {
    "token", "userid", "username", "firstname", "lastname", "email", "currency", "balance",
    "gamesessionid", "gamesessionid", "hash", "bet", "win", "roundid", "gameid", "kind",
    "isroundfinished", "extsystemtransactionid", "casinotransactionid",
}


def _vertical_field_name(value: str) -> bool:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        return False
    lowered = value.casefold()
    if lowered in {"name", "type", "description", "request", "response", "parameters", "values", "optional"}:
        return False
    return bool(re.search(r"[A-Z]", value[1:])) or lowered in _VERTICAL_FIELD_NAMES


def _parse_vertical_parameter_rows(text: str, direction: str, source: str,
                                   absolute_line_offset: int) -> list[dict]:
    """Parse PDF tables where names, types, and descriptions occupy columns.

    MarkItDown may emit a table as one value per line, for example ``userId``
    followed later by ``String`` and its description. The regular row parser
    cannot see that column relationship, so use type markers to associate the
    nearest documented field name.
    """
    lines = text.splitlines()
    type_re = re.compile(r"^(string|number|integer|int|long|float|double|boolean|bool|decimal|object|array|date|datetime)(?:\s+(.*))?$", re.I)
    typed = [(index, line.strip(), type_re.match(line.strip())) for index, line in enumerate(lines)]
    typed = [(index, value, match) for index, value, match in typed if match]
    result = []
    used: set[str] = set()
    inline_re = re.compile(
        r"^([A-Za-z][A-Za-z0-9_]*)\s+(string|number|integer|int|long|float|double|boolean|bool|decimal|object|array|date|datetime)(?:\s+(.*))?$",
        re.I,
    )
    for line_number, line in enumerate(lines):
        inline = inline_re.match(line.strip())
        if not inline or not _vertical_field_name(inline.group(1)):
            continue
        field, type_name, description = inline.groups()
        used.add(field.casefold())
        source_line = absolute_line_offset + line_number + 1
        record = {"name": field, "type": type_name.lower(), "description": description or "",
                  "direction": direction, "required": None, "required_basis": "not specified in source"}
        result.append({"name": field, "direction": direction, "raw": json_text(record),
                       "evidence": evidence(source, source_line, source_line)})
    first_type_line = typed[0][0] if typed else len(lines)
    preamble_fields = [
        (index, line.strip()) for index, line in enumerate(lines[:first_type_line])
        if _vertical_field_name(line.strip()) and line.strip().casefold() not in used
    ]
    preamble_position = 0
    for position, (type_line, type_value, match) in enumerate(typed):
        field_line = None
        field = None
        while preamble_position < len(preamble_fields):
            candidate_line, candidate = preamble_fields[preamble_position]
            preamble_position += 1
            if candidate.casefold() not in used:
                field_line, field = candidate_line, candidate
                break
        for candidate_line in range(type_line - 1, max(-1, type_line - 10), -1):
            if field is not None:
                break
            candidate = lines[candidate_line].strip()
            if _vertical_field_name(candidate) and candidate.casefold() not in used:
                field_line, field = candidate_line, candidate
                break
        if field is None:
            continue
        used.add(field.casefold())
        next_type = typed[position + 1][0] if position + 1 < len(typed) else len(lines)
        fragments = [match.group(2).strip()] if match.group(2) else []
        for value in lines[type_line + 1:next_type]:
            value = value.strip()
            if not value or value.casefold() in {"name", "type", "description"}:
                continue
            if _vertical_field_name(value):
                continue
            if re.search(r"^©|^Page\s+\d+", value, re.I):
                continue
            fragments.append(value)
        line_start = absolute_line_offset + field_line + 1
        line_end = absolute_line_offset + min(next_type, len(lines) - 1) + 1
        record = {"name": field, "type": match.group(1).lower(),
                  "description": " ".join(fragments), "direction": direction,
                  "required": None, "required_basis": "not specified in source"}
        result.append({"name": field, "direction": direction, "raw": json_text(record),
                       "evidence": evidence(source, line_start, line_end)})
    return result


def _append_documented_examples(op: dict, source: str, lines: list[str], occurrence_lines: list[int],
                                section_start: int | None = None, section_end: int | None = None) -> None:
    """Retain URL request examples and XML response examples as evidence."""
    basename = str(op.get("url_or_path", "")).rsplit("/", 1)[-1].split("?", 1)[0].casefold()
    existing = {item.get("raw") for item in op.get("examples", [])}
    for index in occurrence_lines:
        if basename and basename not in lines[index].casefold():
            continue
        if not re.search(r"https?://|/\w+\.do|\b\w+\.do", lines[index], re.I):
            continue
        end = index
        while end + 1 < len(lines) and end - index < 8:
            next_line = lines[end + 1].strip()
            if re.match(r"^(?:©|Page\s+\d+|Expected result|Success:|Fail:|<EXTSYSTEM>)", next_line, re.I):
                break
            end += 1
        raw = "\n".join(lines[index:end + 1]).strip()
        if raw in existing:
            continue
        op["examples"].append({"kind": "request", "raw": raw,
                                "evidence": evidence(source, index + 1, end + 1)})
        existing.add(raw)

    xml_re = re.compile(r"<EXTSYSTEM>.*?</EXTSYSTEM>", re.I | re.S)
    for match in xml_re.finditer(source):
        line_start = source[:match.start()].count("\n")
        if section_start is not None and not (section_start <= line_start < (section_end or len(lines))):
            continue
        if section_start is None and min(abs(line_start - index) for index in occurrence_lines) > 180:
            continue
        raw = match.group(0).strip()
        if raw in existing:
            continue
        kind = "response_error" if re.search(r"<RESULT>\s*ERROR\s*</RESULT>", raw, re.I) else "response_success"
        line_end = line_start + raw.count("\n")
        op["examples"].append({"kind": kind, "raw": raw,
                                "evidence": evidence(source, line_start + 1, line_end + 1)})
        existing.add(raw)


_CALLBACK_HEADING_RE = re.compile(
    r"^\s*[⦁•]\s*(?P<title>Auth\s+Token|Debit|Revision|Credit\s*&\s*Refund|Refund)\s*$",
    re.IGNORECASE,
)


def _extract_callback_heading_operations(doc: dict, source: str, lines: list[str], blocks: list[dict]) -> None:
    """Recover callbacks whose URL is configured outside the document.

    Some PDF manuals use bullet headings such as ``⦁ Debit`` and describe the
    URL as being configured in an external profile page. There is no literal
    URL for the normal path rules to match, but the heading is still reliable
    operation evidence and carries the wallet-flow semantics.
    """
    headings = []
    for index, line in enumerate(lines):
        match = _CALLBACK_HEADING_RE.match(line)
        if match:
            headings.append((index, match.group("title").strip()))
    if not headings:
        return

    existing_names = {str(item.get("operation_name", "")).casefold() for item in doc["operations"]}
    for position, (start, title) in enumerate(headings):
        if title.casefold() in existing_names:
            continue
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        block = next((item for item in blocks if item["line_start"] <= start + 1 <= item["line_end"]), blocks[0])
        name_ref = evidence(source, start + 1, start + 1)
        op = operation(title, None, None, None, name_ref, block["block_id"])
        op["source_section"] = {"number": "", "title": title, "line_start": start + 1, "line_end": end}
        section = "\n".join(lines[start:end])
        op["logic"] = section.strip()
        op["source_description"] = _section_description(op["logic"], title)
        for kind, area_start, area_end in _parameter_areas(section):
            table_offset = start + section[:area_start].count("\n")
            op["parameters"].extend(
                _parse_parameter_rows(section[area_start:area_end], kind, source, table_offset)
            )
        for marker in re.finditer(r"(?im)^\s*(?:Example\s+)?(Request|OK Response|Error Response)\s*:?\s*$", section):
            tail = section[marker.end():]
            opening = tail.find("{")
            if opening < 0 or opening > 100:
                continue
            raw = _balanced_json_object(tail[opening:])
            if raw:
                position_in_section = section.find(raw, marker.end())
                first_line = start + section[:position_in_section].count("\n") + 1
                last_line = first_line + raw.count("\n")
                op["examples"].append({
                    "kind": marker.group(1).strip().lower().replace(" ", "_"),
                    "raw": raw,
                    "evidence": evidence(source, first_line, last_line),
                })
        if title.casefold() == "revision":
            op["adjustment"] = {"type": "ambiguous", "candidates": ["bet_adjustment", "settlement_adjustment", "rollback_adjustment"],
                                  "basis": ["operation is labelled Revision; source path is external"]}
        op["review_status"] = "pending"
        doc["operations"].append(op)
        existing_names.add(title.casefold())


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
    pattern = re.compile(r"(?im)^\s*(?:\d+\.\s*)?(Request(?:\s+(?:data|parameters))?|Response(?:\s+(?:data|parameters))?)\s*:?\s*$")
    for match in pattern.finditer(section):
        kind = "request" if match.group(1).lower().startswith("request") else "response"
        following = section[match.end():match.end() + 240]
        # The first Request: in many manuals introduces METHOD + URL, not fields.
        if kind == "request" and re.search(
                r"(?is)^\s*(?:(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s*:|\{[A-Za-z_]\w*\}\s*/)",
                following):
            continue
        content_start = match.end()
        # PDF tables often place the `Name` column and its first fields before
        # the `Request parameters`/`Response parameters` label.
        prefix_start = max(0, match.start() - 180)
        prefix = section[prefix_start:match.start()]
        names = list(re.finditer(r"(?im)^\s*Name\s*$", prefix))
        if names:
            content_start = prefix_start + names[-1].start()
        headings.append((kind, match.start(), content_start))
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
        # Some PDF tables are flattened into one column: all numeric codes
        # appear first, followed by the descriptions in the same order.
        if not rows:
            section_end = next((index for index in range(start + 1, stop)
                                if "\f" in lines[index]), stop)
            numeric = [(index, line.strip()) for index, line in enumerate(lines[start + 1:section_end], start + 1)
                       if re.fullmatch(r"\d+", line.strip())]
            if len(numeric) < 2:
                continue
            last_code_line = numeric[-1][0]
            descriptions = []
            for index in range(last_code_line + 1, section_end):
                value = lines[index].strip()
                if not value or value.casefold() in {"error code", "description"}:
                    continue
                descriptions.append((index, value))
            for position, (row_index, code) in enumerate(numeric):
                description = descriptions[position][1] if position < len(descriptions) else "Document code entry."
                last_line = descriptions[position][0] if position < len(descriptions) else row_index
                key = (code, "document")
                if key in seen:
                    continue
                doc["error_codes"].append({"code": code, "context": description,
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
    vertical = _parse_vertical_parameter_rows(text, direction, source, absolute_line_offset)
    # Prefer the column-aware interpretation when it recovered more fields;
    # otherwise retain the regular row parser's richer descriptions.
    return vertical if len(vertical) > len(result) else result


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
            # MarkItDown/pdf text extraction may flatten a table row into
            # `name description type required` without separators.
            tokens = line.strip().split()
            if not tokens or not re.fullmatch(r"[A-Za-z_][\w.]*", tokens[0]):
                return None
            type_index = next((i for i, token in enumerate(tokens[1:], 1)
                               if token.lower() in _PARAM_TYPES), None)
            if type_index is None:
                return None
            name = tokens[0]
            type_name = tokens[type_index].lower()
            required_index = next((i for i, token in enumerate(tokens[type_index + 1:], type_index + 1)
                                   if token.lower() in {"mandatory", "optional", "required", "yes", "no", "y", "n"}), None)
            if required_index is not None:
                marker = tokens[required_index].lower()
                required = marker in {"mandatory", "required", "yes", "y"}
                description_parts = [*tokens[1:type_index], *tokens[required_index + 1:]]
            else:
                required = None
                description_parts = tokens[1:type_index]
            description = " ".join(description_parts)
    if not name or name.lower() in {"name", "field", "parameter", "parameters", "values", "mandatory", "required", "description"}:
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
