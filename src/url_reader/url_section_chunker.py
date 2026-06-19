"""Create API-based section chunks from URL Markdown."""

from __future__ import annotations

from typing import Any


def chunk_sections(markdown: str, endpoint_index: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    ordered = sorted(endpoint_index, key=lambda item: item.get("line_index", 0))
    sections = []
    for index, endpoint in enumerate(ordered):
        start = int(endpoint.get("line_index", 0))
        end = int(ordered[index + 1].get("line_index", len(lines))) if index + 1 < len(ordered) else len(lines)
        content = "\n".join(lines[start:end]).strip() or _fallback_window(lines, start)
        sections.append(
            {
                "section_id": f"URL_SEC_{index + 1:03d}",
                "api_name": endpoint.get("api_name", ""),
                "method": endpoint.get("method", ""),
                "endpoint": endpoint.get("endpoint", ""),
                "role": endpoint.get("role", ""),
                "source_url": source_url,
                "content_markdown": content,
                "possible_keywords": endpoint.get("keywords", []),
                "extraction_confidence": endpoint.get("confidence", 0),
            }
        )
    return sections


def _fallback_window(lines: list[str], start: int) -> str:
    return "\n".join(lines[max(0, start - 8) : min(len(lines), start + 40)]).strip()
