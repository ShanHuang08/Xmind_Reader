"""Regex-based endpoint extraction for PDF Markdown."""

from __future__ import annotations

import re
from typing import Any


METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}
ROLE_BY_ENDPOINT = {
    "{baseuri}/authenticate": "authentication",
    "{baseuri}/defence-code": "refresh_token",
    "{baseuri}/terminate": "terminate_session",
    "{baseuri}/balance": "balance",
    "{baseuri}/debit": "bet",
    "{baseuri}/withdraw": "bet",
    "{baseuri}/credit": "settlement",
    "{baseuri}/reverse/withdraw": "rollback",
    "{baseuri}/deposit": "settlement",
}
ROLE_KEYWORD_RULES = (
    ("debit", "bet"),
    ("credit", "settlement"),
)

ENDPOINT_CHARS = r"A-Za-z0-9_./{}:?\-&=%"
METHOD_ENDPOINT_RE = re.compile(
    rf"\b(?P<method>GET|POST|PUT|DELETE|PATCH)\s+(?P<endpoint>/[{ENDPOINT_CHARS}]+)",
    re.IGNORECASE,
)
LABELED_ENDPOINT_RE = re.compile(
    rf"\b(?:endpoint|url|path)\s*[:：]\s*(?:(?P<method>GET|POST|PUT|DELETE|PATCH)\s+)?"
    rf"(?P<endpoint>(?:\{{baseUri\}}|https?://[^/\s|<>]+)?/[{ENDPOINT_CHARS}]+)",
    re.IGNORECASE,
)
API_PATH_RE = re.compile(rf"(?<![\w.])(?P<endpoint>/api/[{ENDPOINT_CHARS}]+)", re.IGNORECASE)
BASE_URI_TABLE_RE = re.compile(
    rf"\|\s*(?:\*\*)?URL(?:\*\*)?\s*\|\s*(?P<endpoint>\{{baseUri\}}/[{ENDPOINT_CHARS}]+)\s*\|",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")


def build_endpoint_index(markdown: str, sections_dir: str = "sections") -> list[dict[str, Any]]:
    candidates = _find_endpoint_candidates(markdown)
    seen = set()
    index = []
    for candidate in candidates:
        key = (candidate["method"], candidate["endpoint"])
        if key in seen:
            continue
        seen.add(key)
        api_name = candidate["api_name"]
        section_file = f"{sections_dir}/{_slugify(api_name or candidate['endpoint'])}.json"
        index.append(
            {
                "api_name": api_name,
                "method": candidate["method"],
                "endpoint": candidate["endpoint"],
                "role": _role_for_candidate(candidate),
                "section_file": section_file,
                "pages": [],
                "keywords": _keywords(api_name, candidate["endpoint"], candidate["context"]),
                "confidence": candidate["confidence"],
                "line_index": candidate["line_index"],
            }
        )
    return index


def _find_endpoint_candidates(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    headings_by_line = _headings_by_line(lines)
    candidates = []
    for index, line in enumerate(lines):
        matches = list(METHOD_ENDPOINT_RE.finditer(line))
        matches.extend(LABELED_ENDPOINT_RE.finditer(line))
        matches.extend(BASE_URI_TABLE_RE.finditer(line))
        if not matches:
            matches.extend(API_PATH_RE.finditer(line))

        for match in matches:
            endpoint = _clean_endpoint(match.group("endpoint"))
            if not endpoint:
                continue
            method = (
                match.groupdict().get("method")
                or _table_method(lines, index)
                or _nearby_method(lines, index)
                or ""
            ).upper()
            if method not in METHODS:
                method = "unknown"
            heading = _nearest_heading(headings_by_line, index) or _api_name_from_endpoint(endpoint)
            context = "\n".join(lines[max(0, index - 6) : min(len(lines), index + 8)])
            candidates.append(
                {
                    "api_name": _clean_api_name(heading, endpoint),
                    "method": method,
                    "endpoint": endpoint,
                    "context": context,
                    "line_index": index,
                    "confidence": _confidence(method, line, heading, endpoint),
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


def _nearest_heading(headings: list[tuple[int, str]], line_index: int) -> str:
    previous = [title for index, title in headings if index <= line_index]
    return previous[-1] if previous else ""


def _nearby_method(lines: list[str], line_index: int) -> str:
    window = " ".join(lines[max(0, line_index - 2) : min(len(lines), line_index + 3)])
    match = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\b", window, re.IGNORECASE)
    return match.group(1) if match else ""


def _table_method(lines: list[str], line_index: int) -> str:
    for line in lines[line_index : min(len(lines), line_index + 8)]:
        match = re.search(
            r"\|\s*(?:\*\*)?Method(?:\*\*)?\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|",
            line,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
    return ""


def _clean_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip().rstrip(".,;)")
    endpoint = endpoint.replace("\\", "/")
    if endpoint.lower().startswith("{baseuri}/"):
        return "{baseUri}/" + endpoint.split("/", 1)[1]
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return endpoint if endpoint.startswith("/") else ""


def _clean_api_name(heading: str, endpoint: str) -> str:
    if heading:
        heading = re.sub(r"[*_`]+", "", heading)
        heading = re.sub(r"^\d+(?:\.\d+)*\s*", "", heading).strip()
        if len(heading) <= 80:
            return heading
    return _api_name_from_endpoint(endpoint)


def _api_name_from_endpoint(endpoint: str) -> str:
    last = endpoint.rstrip("/").rsplit("/", 1)[-1] or "api"
    words = re.split(r"[_\-.]+", last)
    return " ".join(word.capitalize() for word in words if word) + " API"


def _role_for_endpoint(endpoint: str) -> str:
    normalized = endpoint.lower()
    if normalized.startswith("{baseuri}/"):
        normalized = "{baseuri}/" + normalized.split("/", 1)[1]
    direct_role = ROLE_BY_ENDPOINT.get(normalized, "")
    if direct_role:
        return direct_role
    for keyword, role in ROLE_KEYWORD_RULES:
        if keyword in normalized:
            return role
    return ""


def _role_for_candidate(candidate: dict[str, Any]) -> str:
    endpoint_role = _role_for_endpoint(candidate["endpoint"])
    if endpoint_role:
        return endpoint_role
    text = f"{candidate.get('api_name', '')} {candidate.get('context', '')}".lower()
    for keyword, role in ROLE_KEYWORD_RULES:
        if keyword in text:
            return role
    return ""


def _keywords(api_name: str, endpoint: str, context: str) -> list[str]:
    text = f"{api_name} {endpoint} {context}".lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text)
    stop = {"api", "http", "https", "request", "response", "endpoint", "method", "path", "url"}
    result = []
    role = _role_for_endpoint(endpoint)
    if not role:
        for keyword, keyword_role in ROLE_KEYWORD_RULES:
            if keyword in text:
                role = keyword_role
                break
    if role:
        result.append(role)
    for word in words:
        if word in stop or word in result:
            continue
        result.append(word)
        if len(result) >= 12:
            break
    return result


def _confidence(method: str, line: str, heading: str, endpoint: str) -> float:
    score = 0.55
    if method and method != "unknown":
        score += 0.2
    if re.search(r"\b(endpoint|url|path)\b", line, re.IGNORECASE) or "|**URL**|" in line:
        score += 0.1
    if heading:
        score += 0.1
    if _role_for_endpoint(endpoint):
        score += 0.05
    return min(score, 0.95)


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "api_section"
