"""Regex-based endpoint extraction for PDF Markdown."""

from __future__ import annotations

import re
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# Role classification — single source of truth
# ──────────────────────────────────────────────────────────────────────────────
# Maps lowercase keywords (endpoint path segments, API names, request names)
# to canonical roles: authentication, balance, bet, settlement, bet_and_settle,
#                    rollback, refresh_token, terminate_session.
_ROLE_MAP: dict[str, str] = {
    # --- endpoint last-path-segment ---
    "authenticate":       "authentication",
    "auth":               "authentication",
    "gen-signature":      "authentication",
    "gensignature":       "authentication",
    "getaccount":         "authentication",
    "getbalance":         "balance",
    "balance":            "balance",
    "wallet":             "balance",
    "bet":                "bet",
    "debit":              "bet",
    "revision":           "rollback",
    "wager":              "bet",
    "wagerbybatch":       "bet",
    "settle":             "settlement",
    "settlement":         "settlement",
    "credit":             "settlement",
    "result":             "settlement",
    "win":                "settlement",
    "betandresult":       "bet_and_settle",
    "wagerandresult":     "bet_and_settle",
    "cancel":             "rollback",
    "cancelbet":          "rollback",
    "rollback":           "rollback",
    "reversewin":         "rollback",
    "rollbackrollback":   "rollback",
    "refund":             "rollback",
    # --- full baseUri paths (provider-specific) ---
    "{baseuri}/authenticate":   "authentication",
    "{baseuri}/defence-code":   "refresh_token",
    "{baseuri}/terminate":      "terminate_session",
    "{baseuri}/balance":        "balance",
    "{baseuri}/debit":          "bet",
    "{baseuri}/withdraw":       "bet",
    "{baseuri}/credit":         "settlement",
    "{baseuri}/deposit":        "settlement",
    "{baseuri}/reverse/withdraw": "rollback",
}

# Conservative keyword→role pairs used as a LAST-RESORT fallback
# when endpoint path and API name both fail.  Order matters — more
# specific keywords (e.g. "debit") should come before generic ones.
_ROLE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("debit",       "bet"),
    ("revision",    "rollback"),
    ("credit",      "settlement"),
    ("refund",      "rollback"),
    ("auth",        "authentication"),
    ("bet",         "bet"),
    ("wager",       "bet"),
    ("settle",      "settlement"),
    ("win",         "settlement"),
    ("result",      "settlement"),
    ("cancel",      "rollback"),
    ("rollback",    "rollback"),
    ("balance",     "balance"),
    ("authenticate", "authentication"),
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared constants
# ──────────────────────────────────────────────────────────────────────────────
METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH"})
_HTTP_METHODS = r"GET|POST|PUT|DELETE|PATCH"
_EP_CHARS = r"A-Za-z0-9_./{}:?\-&=%"
_GENERIC_HEADINGS = frozenset({
    "endpoint", "endpoints", "request", "response",
    "request body", "response body",
})

# ──────────────────────────────────────────────────────────────────────────────
# Endpoint-detection regexes  (all expose named group ``endpoint``)
# ──────────────────────────────────────────────────────────────────────────────
#
# 1) METHOD_ENDPOINT — inline  METHOD /path  or  METHOD **/path**  (bold)
#    e.g.  "POST /api/v1/games/list"
#          "POST **/games/list**"
#          "| POST | **/games/list** |"   (markdown table cell)
METHOD_ENDPOINT_RE = re.compile(
    rf"\b(?P<method>{_HTTP_METHODS})\s+\*{{0,2}}(?P<endpoint>/[{_EP_CHARS}]+)\*{{0,2}}",
    re.IGNORECASE,
)

# 2) METHOD_FULL_URL — inline  METHOD https://…
#    e.g.  "GET https://api.example.com/v1/games"
METHOD_FULL_URL_RE = re.compile(
    rf"\b(?P<method>{_HTTP_METHODS})\s+(?P<endpoint>https?://[^\s|<>`]+)",
    re.IGNORECASE,
)

# 3) LABELED_ENDPOINT — keyword-labeled endpoint
#    labels : endpoint / endpoints / url / path / 端點地址
#    sep    : colon (:/：) or whitespace
#    value  : full URL | {baseUri}/… | {Interface-URL}/… | /path
#    e.g.  "endpoint: /games/list"
#          "|**Endpoints**||https://{host}/path||||"   (when sep chars align)
LABELED_ENDPOINT_RE = re.compile(
    rf"\b(?:endpoint|endpoints|url|path|端點地址)\s*[:：\s]*"
    rf"(?:(?P<method>{_HTTP_METHODS})\s+)?"
    rf"(?P<endpoint>"
    rf"https?://[^\s|<>`]+"
    rf"|(?:\{{baseUri\}}|\{{Interface-URL\}})/[{_EP_CHARS}]+"
    rf"|/[{_EP_CHARS}]+)",
    re.IGNORECASE,
)

# 4) TABLE_ENDPOINT — markdown-table row
#    e.g.  "| POST | https://host/api/path |"          (full URL)
#          "| POST | **/games/list** |"                  (bold path)
#          "|POST|**/games/list**|"                      (tight table)
#          "|  URL  | {baseUri}/games/list |"            (URL label)
TABLE_ENDPOINT_RE = re.compile(
    rf"\|\s*(?:(?P<method>{_HTTP_METHODS})|(?:\*\*)?URL(?:\*\*)?)\s*\|\s*"
    rf"\*{{0,2}}"
    rf"(?P<endpoint>(?:\{{baseUri\}}|https?://[^/\s|<>]+)?/[{_EP_CHARS}]+)"
    rf"\*{{0,2}}\s*\|",
    re.IGNORECASE,
)

# 5) LABELED_NEXT_LINE_FULL_URL — URL on the line after "Path:" / "Endpoint:".
#    Some Sphinx pages render endpoint fields as:
#      Path:
#      https://{operator-wallet-url}/balance
LABELED_NEXT_LINE_FULL_URL_RE = re.compile(
    r"^\s*(?P<endpoint>https?://[^\s|<>`]+)\s*$",
    re.IGNORECASE,
)

# 5) API_PATH — bare /api/… path (fallback, lowest priority)
#    e.g.  "/api/v1/games/list" in running text
API_PATH_RE = re.compile(
    rf"(?<![\w.])(?P<endpoint>/api/[{_EP_CHARS}]+)",
    re.IGNORECASE,
)

# ──────────────────────────────────────────────────────────────────────────────
# Heading / request detection regexes
# ──────────────────────────────────────────────────────────────────────────────
# Seamless-API method heading  (## GetBalance, ## **Bet**, ## **Refund**, …)
SEAMLESS_METHOD_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:\*{0,2})\s*"
    r"(?P<method_name>GetBalance|Bet|Win|Refund|Rollback|Settle)"
    r"\s*(?:\*{0,2})\s*$",
    re.IGNORECASE,
)

KEYWORD_METHOD_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?:[⦁•]\s*)?(?:\*{0,2})\s*"
    r"(?P<method_name>Auth|Debit|Revision|Credit(?:\s*&\s*Refund)?|Refund)"
    r"\s*(?:\*{0,2})\s*$",
    re.IGNORECASE,
)

CALLBACK_FIELD_RE = re.compile(
    r"\|\s*Auth\s+(?P<name>Debit|Credit|Token)\s*\|",
    re.IGNORECASE,
)

# Legacy transaction heading  (Groove-style: "WAGER", "ROLLBACK ON RESULT", …)
TRANSACTION_HEADING_RE = re.compile(
    r"^(?P<title>GET ACCOUNT|GET BALANCE|WAGER|RESULT|WAGER AND RESULT"
    r"|ROLLBACK|JACKPOT|ROLLBACK ON RESULT|ROLLBACK ON ROLLBACK|BET BY BATCH)\s*$",
    re.IGNORECASE,
)

# Request parameter  (?request=Wager)
REQUEST_QUERY_RE = re.compile(
    r"\brequest\s*=\s*(?P<request>[A-Za-z][A-Za-z0-9_]*)",
    re.IGNORECASE,
)

# Generic markdown heading
HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$")


def build_endpoint_index(markdown: str, sections_dir: str = "sections") -> list[dict[str, Any]]:
    candidates = _find_endpoint_candidates(markdown)
    best_candidates: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        # For shared base URLs, differentiate candidates by api_name when it
        # maps to a known role (e.g. Bet vs Win vs Refund on /{Partner_base_URL}).
        endpoint_lower = candidate["endpoint"].lower()
        api_name_lower = candidate.get("api_name", "").lower()
        _shared_bases = ("/{partner_base_url}", "/{partner_base_url}/")
        if endpoint_lower in _shared_bases and api_name_lower in _ROLE_MAP:
            key = (candidate["method"].lower(), f"{endpoint_lower}#{api_name_lower}")
        else:
            key = (candidate["method"].lower(), endpoint_lower)
        current = best_candidates.get(key)
        if current is None or _candidate_rank(candidate) > _candidate_rank(current):
            best_candidates[key] = candidate

    index = []
    for candidate in sorted(best_candidates.values(), key=lambda item: item.get("line_index", 0)):
        api_name = candidate["api_name"]
        section_file = f"{sections_dir}/{_slugify(api_name or candidate['endpoint'])}.json"
        index.append(
            {
                "api_name": api_name,
                "method": candidate["method"],
                "endpoint": candidate["endpoint"],
                "role": _resolve_role(candidate["endpoint"], candidate.get("api_name", ""), candidate.get("context", "")),
                "section_file": section_file,
                "pages": [],
                "keywords": _keywords(api_name, candidate["endpoint"], candidate["context"]),
                "confidence": candidate["confidence"],
                "line_index": candidate["line_index"],
            }
        )
    return index


def _candidate_rank(candidate: dict[str, Any]) -> tuple[float, int]:
    api_name = candidate.get("api_name", "")
    line_index = int(candidate.get("line_index", 0))
    confidence = float(candidate.get("confidence", 0))
    heading_bonus = 0.1 if api_name and not api_name.lower().startswith("page ") else 0
    return (confidence + heading_bonus, line_index)


def _find_endpoint_candidates(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    headings_by_line = _headings_by_line(lines)
    candidates = []
    for index, line in enumerate(lines):
        if line.strip().lower().startswith("source url:"):
            continue
        matches = list(METHOD_ENDPOINT_RE.finditer(line))
        matches.extend(METHOD_FULL_URL_RE.finditer(line))
        matches.extend(LABELED_ENDPOINT_RE.finditer(line))
        matches.extend(TABLE_ENDPOINT_RE.finditer(line))
        adjacent_url_match = _labeled_next_line_url_match(lines, index)
        if adjacent_url_match:
            matches.append(adjacent_url_match)
        if not matches:
            matches.extend(API_PATH_RE.finditer(line))

        for match in matches:
            endpoint = _clean_endpoint(match.group("endpoint"))
            if not endpoint:
                continue
            context = "\n".join(lines[max(0, index - 6) : min(len(lines), index + 8)])
            endpoint = _repair_endpoint_from_context(endpoint, context)
            method = (
                match.groupdict().get("method")
                or _table_method(lines, index)
                or _nearby_method(lines, index)
                or ""
            ).upper()
            if method not in METHODS:
                method = "unknown"
            heading = _nearest_heading(headings_by_line, index) or _api_name_from_endpoint(endpoint)
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

        heading_match = TRANSACTION_HEADING_RE.match(line.strip())
        if heading_match:
            title = _clean_transaction_title(heading_match.group("title"))
            request_name = _request_from_title(title)
            if request_name:
                candidates.append(
                    {
                        "api_name": title,
                        "method": _nearby_method(lines, index) or _document_method(lines) or "GET",
                        "endpoint": f"request:{request_name}",
                        "context": "\n".join(lines[index : min(len(lines), index + 12)]),
                        "line_index": index,
                        "confidence": 0.9,
                    }
                )

        request_match = REQUEST_QUERY_RE.search(line)
        if request_match:
            request_name = request_match.group("request")
            candidates.append(
                {
                    "api_name": _api_name_from_request(request_name),
                    "method": _nearby_method(lines, index) or _document_method(lines) or "GET",
                    "endpoint": f"request:{request_name}",
                    "context": "\n".join(lines[max(0, index - 4) : min(len(lines), index + 8)]),
                    "line_index": index,
                    "confidence": 0.85,
                }
            )

        # Detect Seamless API method headings (## Bet, ## Win, ## Refund, ## GetBalance)
        seamless_match = SEAMLESS_METHOD_HEADING_RE.match(line.strip())
        if seamless_match:
            method_name = seamless_match.group("method_name")
            base_url = _find_seamless_base_url(lines, index)
            context = "\n".join(lines[index : min(len(lines), index + 15)])
            candidates.append(
                {
                    "api_name": method_name,
                    "method": _nearby_method(lines, index) or "POST",
                    "endpoint": base_url or f"/{{Partner_base_URL}}/{method_name}",
                    "context": context,
                    "line_index": index,
                    "confidence": 0.90,
                }
            )

        keyword_heading_match = KEYWORD_METHOD_HEADING_RE.match(line.strip())
        if keyword_heading_match:
            method_names = _keyword_method_names(keyword_heading_match.group("method_name"))
            context = "\n".join(lines[index : min(len(lines), index + 24)])
            for method_name in method_names:
                candidates.append(
                    {
                        "api_name": method_name.title(),
                        "method": _nearby_method(lines, index) or "POST",
                        "endpoint": f"keyword:{method_name}",
                        "context": context,
                        "line_index": index,
                        "confidence": 0.88,
                    }
                )

        callback_match = CALLBACK_FIELD_RE.search(line)
        if callback_match:
            method_name = _callback_field_method(callback_match.group("name"))
            context = "\n".join(lines[max(0, index - 4) : min(len(lines), index + 8)])
            candidates.append(
                {
                    "api_name": method_name.title(),
                    "method": "POST",
                    "endpoint": f"keyword:{method_name}",
                    "context": context,
                    "line_index": index,
                    "confidence": 0.78,
                }
            )
    return candidates


def _keyword_method_names(raw_name: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", raw_name.strip().lower())
    if normalized == "credit & refund":
        return ["credit", "refund"]
    return [normalized.replace(" ", "_")]


def _callback_field_method(raw_name: str) -> str:
    normalized = raw_name.strip().lower()
    if normalized == "token":
        return "auth"
    return normalized


def _find_seamless_base_url(lines: list[str], current_line: int) -> str:
    """Search backwards for a table row like |POST|**/{Partner_base_URL}**| to reuse as shared endpoint.
    Skips lines inside code blocks (indented or fenced) to avoid picking up example URLs."""
    for line in reversed(lines[max(0, current_line - 40) : current_line]):
        stripped = line.strip()
        # Skip fenced code blocks and indented code lines
        if stripped.startswith("```") or stripped.startswith("{") or stripped.startswith('"'):
            continue
        match = METHOD_ENDPOINT_RE.search(line)
        if match:
            return match.group("endpoint")
    return ""


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


def _labeled_next_line_url_match(lines: list[str], line_index: int) -> re.Match[str] | None:
    line = lines[line_index].strip()
    if not line.startswith(("http://", "https://")):
        return None
    previous = _previous_non_empty_line(lines, line_index)
    if not re.match(r"^(?:path|endpoint|endpoints|url|端點地址)\s*[:：]?\s*$", previous, re.IGNORECASE):
        return None
    return LABELED_NEXT_LINE_FULL_URL_RE.match(line)


def _previous_non_empty_line(lines: list[str], line_index: int) -> str:
    for line in reversed(lines[max(0, line_index - 6) : line_index]):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _nearby_method(lines: list[str], line_index: int) -> str:
    window = " ".join(lines[max(0, line_index - 4) : min(len(lines), line_index + 8)])
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
    endpoint = re.sub(r"/\s+", "/", endpoint)
    endpoint = endpoint.replace("\\", "/")
    if endpoint.lower().startswith("{baseuri}/"):
        return "{baseUri}/" + endpoint.split("/", 1)[1]
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return endpoint if endpoint.startswith("/") else ""


def _repair_endpoint_from_context(endpoint: str, context: str) -> str:
    if not endpoint.endswith("/"):
        return endpoint
    match = re.search(
        r"(?:Endpoints|端點地址)\s+"
        + re.escape(endpoint)
        + r"\s+(?P<tail>[A-Za-z][A-Za-z0-9_/-]*)",
        context,
        re.IGNORECASE,
    )
    if match:
        return endpoint + match.group("tail").lstrip("/")
    return endpoint


def _clean_transaction_title(title: str) -> str:
    return " ".join(word.capitalize() for word in title.lower().split())


def _request_from_title(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", title.lower())
    title_map = {
        "getaccount": "getaccount",
        "getbalance": "getbalance",
        "wager": "wager",
        "result": "result",
        "wagerandresult": "wagerAndResult",
        "rollback": "rollback",
        "jackpot": "jackpot",
        "rollbackonresult": "reversewin",
        "rollbackonrollback": "rollbackrollback",
        "betbybatch": "wagerbybatch",
    }
    return title_map.get(normalized, "")


def _api_name_from_request(request_name: str) -> str:
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", request_name)
    return " ".join(word.capitalize() for word in words) or request_name


def _document_method(lines: list[str]) -> str:
    for line in lines[:80]:
        match = re.search(r"\bHTTP Method:\s*(GET|POST|PUT|DELETE|PATCH)\b", line, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def _clean_api_name(heading: str, endpoint: str) -> str:
    if heading:
        heading = re.sub(r"[*_`]+", "", heading)
        heading = heading.replace("¶", "")
        heading = re.sub(r"^\d+(?:\.\d+)*\s*", "", heading).strip()
        if heading and heading.lower() not in _GENERIC_HEADINGS and len(heading) <= 80:
            return heading
    return _api_name_from_endpoint(endpoint)


def _api_name_from_endpoint(endpoint: str) -> str:
    last = endpoint.rstrip("/").rsplit("/", 1)[-1] or "api"
    words = re.split(r"[_\-.]+", last)
    return " ".join(word.capitalize() for word in words if word) + " API"


def _resolve_role(endpoint: str, api_name: str = "", context: str = "") -> str:
    """Determine role from endpoint path, API name, or keyword scan (in priority order)."""
    text = endpoint.lower()
    # 1. request:xxx pseudo-endpoints
    if text.startswith("request:"):
        return _ROLE_MAP.get(text.split(":", 1)[1], "")
    if text.startswith("keyword:"):
        return _ROLE_MAP.get(text.split(":", 1)[1], "")
    # 2. Last segment of URL path
    path = text.split("?", 1)[0].rstrip("/")
    role = _ROLE_MAP.get(path.rsplit("/", 1)[-1])
    if role:
        return role
    # 3. Normalised {baseUri}/… full path
    if "{baseuri}/" in text:
        base_path = "{baseuri}/" + text.split("{baseuri}/", 1)[1]
        role = _ROLE_MAP.get(base_path)
        if role:
            return role
    # 4. API name (handles shared-endpoint seamless methods)
    if api_name:
        role = _ROLE_MAP.get(api_name.lower())
        if role:
            return role
    # 5. Keyword scan (conservative, ordered by specificity)
    scan = f"{api_name} {endpoint} {context}".lower()
    for keyword, r in _ROLE_KEYWORDS:
        if keyword in scan:
            return r
    return ""


def _keywords(api_name: str, endpoint: str, context: str) -> list[str]:
    text = f"{api_name} {endpoint} {context}".lower()
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text)
    stop = {"api", "http", "https", "request", "response", "endpoint", "method", "path", "url"}
    result = []
    role = _resolve_role(endpoint, api_name, context)
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
    if _resolve_role(endpoint):
        score += 0.05
    return min(score, 0.95)


def _slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "api_section"
