"""Extract wallet action sections from URL Markdown docs."""

from __future__ import annotations

import re
from typing import Any


ACTION_ROLE = {
    "balance": "balance",
    "bet": "bet",
    "win": "settlement",
    "cancel": "rollback",
    "cancelwin": "rollback",
    "betandwin": "bet_and_settle",
    "cancelbetandwin": "rollback",
}

ACTION_RE = re.compile(r"\baction\s*:\s*(?P<action>[A-Za-z][A-Za-z0-9_]*)", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")


def build_action_index(markdown: str, sections_dir: str = "sections") -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    headings = _headings_by_line(lines)
    candidates = []
    seen = set()
    for index, line in enumerate(lines):
        match = ACTION_RE.search(line)
        if not match:
            continue
        action = match.group("action")
        action_key = action.lower()
        if action_key in seen:
            continue
        seen.add(action_key)
        heading_index, heading = _nearest_heading(headings, index)
        heading = heading or _api_name_from_action(action)
        section_start = heading_index if heading_index >= 0 and index - heading_index <= 8 else index
        api_name = _clean_api_name(heading, action)
        candidates.append(
            {
                "api_name": api_name,
                "method": _nearby_method(lines, index) or "POST",
                "endpoint": f"action:{action}",
                "role": ACTION_ROLE.get(action_key, ""),
                "section_file": f"{sections_dir}/{_slugify(api_name or action)}.json",
                "pages": [],
                "keywords": _keywords(api_name, action),
                "confidence": 0.9,
                "line_index": section_start,
            }
        )
    return candidates


def _headings_by_line(lines: list[str]) -> list[tuple[int, str]]:
    headings = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line.strip())
        if match:
            headings.append((index, match.group("title").strip()))
    return headings


def _nearest_heading(headings: list[tuple[int, str]], line_index: int) -> tuple[int, str]:
    previous = [(index, title) for index, title in headings if index <= line_index]
    return previous[-1] if previous else (-1, "")


def _nearby_method(lines: list[str], line_index: int) -> str:
    window = " ".join(lines[max(0, line_index - 4) : min(len(lines), line_index + 5)])
    match = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\b", window, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _clean_api_name(heading: str, action: str) -> str:
    heading = re.sub(r"[\u200b-\u200f\ufeff]", "", heading)
    heading = re.sub(r"[*_`?]+", "", heading).strip()
    if heading and len(heading) <= 80:
        return heading
    return _api_name_from_action(action)


def _api_name_from_action(action: str) -> str:
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", action)
    return " ".join(word.capitalize() for word in words) + " Action"


def _keywords(api_name: str, action: str) -> list[str]:
    result = []
    role = ACTION_ROLE.get(action.lower(), "")
    if role:
        result.append(role)
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", f"{api_name} {action}".lower()):
        if word not in result:
            result.append(word)
        if len(result) >= 12:
            break
    return result


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "api_section"
