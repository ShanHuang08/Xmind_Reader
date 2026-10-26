"""One serialization contract: authoritative JSON plus a verified reading view."""
from .contracts import MARKER, SCHEMA, json_text, validate_document
import json


def fence(text: str, language: str = "text") -> str:
    import re
    size = max([len(x) for x in re.findall(r"`+", text)] + [2]) + 1
    token = "`" * size
    return f"{token}{language}\n{text}\n{token}\n"


def render_canonical_markdown(doc: dict) -> str:
    validate_document(doc)
    parts = [f"{MARKER}{SCHEMA} -->\n", "# Vendor document\n",
             "<details>\n<summary>Machine-readable document contract (includes complete source provenance)</summary>\n\n",
             fence(json_text(doc), "json"), "</details>\n", "## Endpoint selection\n",
             fence(json_text(doc.get("extensions", {}).get("endpoint_selection", {}), ), "json"), "## Operations\n"]
    for op in doc["operations"]:
        parts.extend([f"### Operation: {op['operation_id']}\n",
                      f"#### {op['operation_name']}\n",
                      "", "| Field | Value |", "|---|---|",
                      f"| Method | `{op.get('http_method') or 'unknown'}` |",
                      f"| Endpoint | `{op.get('url_or_path') or 'unknown'}` |",
                      f"| Role | `{op.get('role') or 'unclassified'}` ({op.get('role_confidence', 'none')} confidence) |",
                      f"| Selection | `{op.get('selection_status', 'unclassified')}` — {op.get('selection_reason', '')} |",
                      f"| Review | `{op.get('review_status', 'pending')}` |", ""])
        if op.get("source_description"):
            parts.extend(["#### Purpose from source\n", op["source_description"], ""])
        if op.get("usage_logic"):
            parts.extend(["#### Wallet-flow usage\n", op["usage_logic"], ""])
        for direction, heading in (("request", "Request parameters"), ("response", "Response parameters")):
            parameters = [_parameter_record(item) for item in op.get("parameters", [])
                          if item.get("direction") == direction]
            if parameters:
                parts.extend([f"#### {heading}\n", "| Name | Type | Required | Description |", "|---|---|---|---|"])
                for item in parameters:
                    parts.append("| " + " | ".join(_cell(value) for value in
                        (item.get("name"), item.get("type"), item.get("required"), item.get("description"))) + " |")
                parts.append("")
        if op.get("examples"):
            parts.append("#### API examples\n")
            for example in op["examples"]:
                label = {"request": "Request example", "ok_response": "Success response example",
                         "error_response": "Error response example"}.get(example.get("kind"), example.get("kind", "Example"))
                parts.extend([f"##### {label}\n", fence(example.get("raw", ""), "json")])
        if op.get("status_codes"):
            parts.extend(["#### Status codes\n", ", ".join(f"`{x}`" for x in op["status_codes"]), ""])
        if op.get("logic"):
            parts.extend(["#### Source section details\n", fence(op["logic"], "markdown")])
        section = op.get("source_section", {})
        parts.extend([f"Source: `{section.get('number', '')}` lines {section.get('line_start', '?')}–{section.get('line_end', '?')}\n",
                      "#### Source evidence\n", fence(json_text(op["evidence"]), "json")])
    parts.extend(["## Error codes\n", fence(json_text(doc["error_codes"]), "json"),
                  "<details>\n<summary>Original converted source and unmapped content (all discovered APIs)</summary>\n\n",
                  fence(doc["source_markdown"], "markdown"), "</details>"])
    return "\n".join(parts)


def _parameter_record(item: dict) -> dict:
    try:
        value = json.loads(item.get("raw", "{}"))
    except (TypeError, json.JSONDecodeError):
        value = {}
    required = value.get("required")
    if required is None:
        required = False
    return {**value, "name": value.get("name", item.get("name", "")),
            "type": value.get("type"), "required": required,
            "description": value.get("description", "")}


def _cell(value) -> str:
    if value is None:
        value = "unknown"
    elif isinstance(value, bool):
        value = "Y" if value else "N"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()
