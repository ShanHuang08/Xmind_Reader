"""Build URL reader outputs from OpenAPI JSON documents."""

from __future__ import annotations

import re
from typing import Any


def openapi_to_markdown(data: dict[str, Any], source_url: str) -> str:
    title = data.get("info", {}).get("title") or "OpenAPI Document"
    lines = [f"# {title}", "", f"Source URL: {source_url}", ""]
    paths = data.get("paths", {})
    if not isinstance(paths, dict):
        return "\n".join(lines)

    for path, operations in paths.items():
        if not isinstance(operations, dict):
            continue
        for method, operation in operations.items():
            if method.upper() not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                continue
            operation = operation if isinstance(operation, dict) else {}
            api_name = operation.get("summary") or operation.get("operationId") or _api_name_from_path(path)
            lines.extend([f"## {api_name}", "", f"Method: {method.upper()}", "", f"Endpoint: {path}", ""])

            parameters = operation.get("parameters", [])
            if parameters:
                lines.extend(["### Request Parameters", "", "| Name | In | Required | Type | Description |", "|---|---|---|---|---|"])
                for param in parameters:
                    if not isinstance(param, dict):
                        continue
                    schema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
                    lines.append(
                        "| {name} | {where} | {required} | {type_} | {description} |".format(
                            name=param.get("name", ""),
                            where=param.get("in", ""),
                            required=param.get("required", False),
                            type_=schema.get("type", ""),
                            description=_clean(param.get("description", "")),
                        )
                    )
                lines.append("")

            request_body = operation.get("requestBody", {})
            if isinstance(request_body, dict) and request_body:
                lines.extend(["### Request Body", "", "```json", _clean(str(request_body)), "```", ""])

            responses = operation.get("responses", {})
            if isinstance(responses, dict) and responses:
                lines.extend(["### Responses", "", "| Code | Description |", "|---|---|"])
                for code, response in responses.items():
                    description = response.get("description", "") if isinstance(response, dict) else str(response)
                    lines.append(f"| {code} | {_clean(description)} |")
                lines.append("")
    return "\n".join(lines).strip() + "\n"


def _api_name_from_path(path: str) -> str:
    last = path.rstrip("/").rsplit("/", 1)[-1] or "api"
    return " ".join(part.capitalize() for part in re.split(r"[_\-.{}]+", last) if part) + " API"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace("|", "\\|").strip()
