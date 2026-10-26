"""The initial canonical contract. No PDF/layout or vendor heuristics here."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

SCHEMA = "vendor-markdown/v1"
VERSION = "1"
MARKER = "<!-- vendor-markdown:"
FACTS = ("operation_name", "http_method", "url_or_path", "discriminator", "role")
REVIEWS = {"pending", "rule_verified", "accepted", "rejected"}


class ContractError(ValueError):
    """Invalid structure, provenance, or artifact integrity."""


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def digest(value: Any) -> str:
    raw = value if isinstance(value, bytes) else (
        value.encode("utf-8") if isinstance(value, str) else json_text(value).encode("utf-8")
    )
    return hashlib.sha256(raw).hexdigest()


def strict_json(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ContractError(f"Invalid JSON constant: {value}")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractError("Invalid JSON") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def identifier(value: str) -> str:
    require(isinstance(value, str) and bool(re.fullmatch(r"[\w-]{1,100}", value)),
            "Identifiers must be 1–100 letters, numbers, underscores or hyphens")
    require(value.upper() not in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)],
                                  *[f"LPT{i}" for i in range(10)]}, "Reserved identifier")
    return value


def evidence(text: str, start: int, end: int) -> dict:
    return {"source_sha256": digest(text), "line_start": start, "line_end": end,
            "quote": "\n".join(text.splitlines()[start - 1:end])}


def validate_evidence(item: dict, source: str | None) -> None:
    require(isinstance(item, dict), "Evidence must be an object")
    require(bool(re.fullmatch(r"[a-f0-9]{64}", str(item.get("source_sha256", "")))), "Invalid evidence hash")
    a, b = item.get("line_start"), item.get("line_end")
    require(type(a) is int and type(b) is int and 1 <= a <= b, "Invalid evidence line range")
    require(isinstance(item.get("quote"), str) and bool(item["quote"].strip()), "Evidence quote required")
    if source is not None:
        require(item["source_sha256"] == digest(source), "Evidence source hash mismatch")
        require(b <= len(source.splitlines()), "Evidence line outside source")
        require(item["quote"] == "\n".join(source.splitlines()[a - 1:b]), "Evidence quote mismatch")


def new_document(meta: dict, source: str, blocks: list[dict]) -> dict:
    return {"schema_version": SCHEMA, "vendor": meta["vendor"], "source_id": meta["source_id"],
            "source_origin": meta["origin"], "conversion_id": meta["conversion_id"],
            "converted_sha256": digest(source), "normalization_id": "", "status": "partial",
            "source_markdown": source, "operations": [], "error_codes": [],
            "coverage": [{**b, "state": "pending", "reason": "Not reviewed"} for b in blocks],
            "extensions": {}, "strategy": {"id": "rules", "version": VERSION}}


def document_status(doc: dict) -> str:
    pending = any(x["state"] == "pending" for x in doc["coverage"])
    pending |= any(x["review_status"] == "pending" for x in doc["operations"] + doc["error_codes"])
    pending |= any(not op.get("http_method") or not op.get("url_or_path") or
                   (op.get("discriminator") and op["discriminator"].get("location") == "unknown")
                   for op in doc["operations"] if op["review_status"] != "rejected")
    return "partial" if pending else "complete"


def validate_document(doc: dict, source: str | None = None) -> None:
    require(isinstance(doc, dict) and doc.get("schema_version") == SCHEMA, "Unsupported canonical schema")
    for field in ("vendor", "source_id"):
        identifier(doc.get(field))
    require(doc.get("source_origin") in {"pdf", "html", "markdown", "openapi"}, "Invalid origin")
    require(isinstance(doc.get("source_markdown"), str), "Source Markdown must be retained")
    require(doc.get("converted_sha256") == digest(doc["source_markdown"]), "Embedded source hash mismatch")
    if source is not None:
        require(source == doc["source_markdown"], "Source differs from conversion")
    require(isinstance(doc.get("strategy"), dict) and isinstance(doc.get("extensions"), dict), "Missing strategy/extensions")
    evidence_sources = {digest(doc["source_markdown"]): doc["source_markdown"]}
    for item in doc["extensions"].get("supplemental_sources", []):
        require(isinstance(item, dict) and isinstance(item.get("content_markdown"), str), "Invalid supplemental source")
        content = item["content_markdown"]
        require(item.get("sha256") == digest(content), "Supplemental source hash mismatch")
        evidence_sources[item["sha256"]] = content
    for key in ("conversion_id", "normalization_id"):
        require(isinstance(doc.get(key), str), f"Missing {key}")
    for key in ("operations", "error_codes", "coverage"):
        require(isinstance(doc.get(key), list), f"Missing {key}")
    covered = set()
    block_ids = set()
    source_lines = doc["source_markdown"].splitlines()
    for block in doc["coverage"]:
        require(isinstance(block, dict), "Invalid coverage block")
        identifier(block.get("block_id"))
        require(block["block_id"] not in block_ids, "Duplicate block ID")
        block_ids.add(block["block_id"])
        a, b = block.get("line_start"), block.get("line_end")
        require(type(a) is int and type(b) is int and 1 <= a <= b <= len(source_lines), "Invalid block range")
        require(not covered.intersection(range(a, b + 1)), "Overlapping source blocks")
        covered.update(range(a, b + 1))
        require(block.get("state") in {"mapped", "retained_unmapped", "excluded_with_reason", "pending"}, "Invalid coverage state")
        require(isinstance(block.get("reason"), str) and bool(block["reason"].strip()), "Coverage reason required")
    require(covered == set(range(1, len(source_lines) + 1)), "Coverage must account for every source line")
    ids = set()
    for op in doc["operations"]:
        require(isinstance(op, dict), "Invalid operation")
        require(all(key in op for key in FACTS), "All operation fields must be present; use null for unknown facts")
        identifier(op.get("operation_id"))
        require(op["operation_id"] not in ids, "Duplicate operation ID")
        ids.add(op["operation_id"])
        require(isinstance(op.get("operation_name"), str) and bool(op["operation_name"].strip()), "Operation name required")
        require(op.get("http_method") in {None, "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}, "Invalid HTTP method")
        for key in ("url_or_path", "role"):
            require(op.get(key) is None or isinstance(op[key], str), f"Invalid {key}")
        d = op.get("discriminator")
        require(d is None or (isinstance(d, dict) and set(d) == {"location", "name", "value"}
                            and all(isinstance(v, str) and v for v in d.values())
                            and d["location"] in {"body", "query", "header", "unknown"}), "Invalid discriminator")
        require(op.get("review_status") in REVIEWS, "Invalid operation review status")
        require(isinstance(op.get("section_ids"), list) and bool(op["section_ids"])
                and set(op["section_ids"]) <= block_ids, "Invalid section references")
        require(isinstance(op.get("evidence"), dict), "Operation evidence required")
        for key in FACTS:
            value = op.get(key)
            if value is None:
                continue
            refs = op["evidence"].get(key)
            require(isinstance(refs, list) and bool(refs), f"Evidence required for {key}")
            for ref in refs:
                evidence_text = evidence_sources.get(ref.get("source_sha256"))
                require(evidence_text is not None, "Evidence does not refer to a retained source")
                validate_evidence(ref, evidence_text)
            quote = "\n".join(x["quote"] for x in refs)
            # Classification is a reviewed inference; literal method/path/discriminator must exist.
            if key in {"http_method", "url_or_path"}:
                require(str(value).casefold() in quote.casefold(), f"{key} not supported by quote")
            if key == "discriminator":
                require(value["name"] in quote and value["value"] in quote, "Discriminator lacks evidence")
        for key in ("parameters", "examples"):
            require(isinstance(op.get(key), list), f"Missing {key}")
            for item in op[key]:
                require(isinstance(item, dict) and isinstance(item.get("raw"), str), f"{key} requires raw content")
                item_ref = item.get("evidence")
                item_source = evidence_sources.get(item_ref.get("source_sha256")) if isinstance(item_ref, dict) else None
                require(item_source is not None, "Example/parameter evidence does not refer to a retained source")
                validate_evidence(item_ref, item_source)
    for row in doc["error_codes"]:
        require(isinstance(row, dict) and isinstance(row.get("code"), str), "Error code must be a string")
        require(isinstance(row.get("context"), str), "Error context required")
        require(row.get("scope") == "document" or row.get("scope") in ids, "Invalid error-code scope")
        require(row.get("review_status") in REVIEWS, "Invalid error review status")
        require(row.get("response_json") is None or isinstance(row["response_json"], (dict, list)), "Invalid response JSON")
        error_ref = row.get("evidence")
        error_source = evidence_sources.get(error_ref.get("source_sha256")) if isinstance(error_ref, dict) else None
        require(error_source is not None, "Error-code evidence does not refer to a retained source")
        validate_evidence(error_ref, error_source)
        require(row["code"] in row["evidence"]["quote"], "Error code lacks evidence")
    require(doc.get("status") == document_status(doc), "Status disagrees with coverage/review")


def payload_hash(doc: dict) -> str:
    value = deepcopy(doc)
    value.pop("normalization_id", None)
    return digest(value)
