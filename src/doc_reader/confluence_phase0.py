"""Read-only Phase 0 capability spike for Atlassian Rovo MCP and Confluence REST.

This module is deliberately isolated from the production document pipeline.  It records
schemas, hashes, counts, and gate decisions; it never persists page bodies or credentials.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REQUIRED_TOOLS = frozenset({"getAccessibleAtlassianResources", "getConfluencePage"})
REQUIRED_FIXTURE_KINDS = frozenset(
    {
        "basic_content",
        "parameter_table",
        "code_examples",
        "merged_nested_table",
        "tasks",
        "macro",
        "embedded_content",
        "empty_error",
        "long_content",
    }
)
REQUIRED_ADMIN_CHECKS = frozenset(
    {
        "api_token_auth_enabled",
        "confluence_read_enabled",
        "ip_allowlist_verified",
        "service_account_product_access",
        "fixture_pages_readable",
        "negative_control_invisible",
        "least_privilege_scopes_verified",
        "audit_log_identity_visible",
    }
)
REQUIRED_FAILURE_OBSERVATIONS = frozenset(
    {
        "authentication",
        "authorization",
        "not_found_or_invisible",
        "rate_limit",
        "transport",
        "missing_tool",
        "schema_mismatch",
        "empty_page",
        "malformed_payload",
        "truncated_payload",
        "cursor_loop",
        "safety_limit",
        "version_mismatch",
        "rest_failure",
        "async_context",
    }
)
SECRET_ENV_NAMES = frozenset(
    {
        "ROVO_MCP_API_KEY",
        "ROVO_MCP_API_TOKEN",
        "ROVO_MCP_EMAIL",
        "CONFLUENCE_REST_API_TOKEN",
        "CONFLUENCE_REST_EMAIL",
        "CONFLUENCE_REST_BEARER_TOKEN",
    }
)
_MARKDOWN_KEY_NAMES = frozenset({"markdown", "body", "content", "value", "text"})
_CURSOR_NAMES = frozenset({"cursor", "next", "nextcursor", "continuationtoken"})
_COMPLETED_STOP_REASONS = frozenset({"completed", "complete", "done", "end", "stop", "finished"})


class Phase0Error(RuntimeError):
    """Base error for the isolated spike."""


class Phase0ConfigurationError(Phase0Error):
    pass


class Phase0CapabilityError(Phase0Error):
    pass


class Phase0ResponseError(Phase0Error):
    pass


class Phase0TruncationError(Phase0ResponseError):
    pass


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    kind: str
    url: str
    readable: bool = True
    required: bool = True
    markers: tuple[str, ...] = ()
    end_marker: str = ""
    expected_min: Mapping[str, int] = field(default_factory=dict)

    @property
    def page_id(self) -> str:
        return parse_numeric_page_id(self.url)

    @property
    def site_host(self) -> str:
        return validate_https_site_url(self.url)


@dataclass(frozen=True)
class Phase0Manifest:
    schema_version: int
    fixtures: tuple[FixtureSpec, ...]


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    endpoint: str
    authorization: str
    allowed_sites: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True)
class RestConfig:
    auth_mode: str
    authorization: str
    timeout_seconds: float


@dataclass(frozen=True)
class MarkdownCandidate:
    location: str
    text: str

    def summary(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "char_count": len(self.text),
            "byte_count": len(self.text.encode("utf-8")),
            "sha256": sha256_text(self.text),
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_identifier(value: str) -> str:
    return sha256_text(value)[:16]


def validate_https_site_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise Phase0ConfigurationError("Confluence URLs must use HTTPS and include a host")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise Phase0ConfigurationError("Confluence URLs cannot include user-info or a non-default port")
    host = parsed.hostname.lower().rstrip(".")
    if not host.endswith(".atlassian.net"):
        raise Phase0ConfigurationError("Confluence host must be an explicit atlassian.net site")
    return host


def parse_numeric_page_id(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    validate_https_site_url(url)
    segments = [urllib.parse.unquote(segment) for segment in parsed.path.split("/") if segment]
    if len(segments) >= 6 and segments[:2] == ["wiki", "spaces"] and segments[3] == "pages":
        page_id = segments[4]
    elif segments == ["wiki", "pages", "viewpage.action"]:
        values = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("pageId", [])
        if len(values) != 1:
            raise Phase0ConfigurationError("viewpage.action URL must contain one pageId")
        page_id = values[0]
    else:
        raise Phase0ConfigurationError("Phase 0 manifest requires a canonical or viewpage URL with numeric page ID")
    if not re.fullmatch(r"[1-9][0-9]*", page_id):
        raise Phase0ConfigurationError("Confluence page ID must be a positive integer")
    return page_id


def load_manifest(path: Path) -> Phase0Manifest:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("fixtures"), list):
        raise Phase0ConfigurationError("Phase 0 manifest must use schema_version 1 and contain fixtures")
    fixtures: list[FixtureSpec] = []
    names: set[str] = set()
    for item in raw["fixtures"]:
        if not isinstance(item, dict):
            raise Phase0ConfigurationError("Each fixture must be an object")
        name = str(item.get("name", "")).strip()
        kind = str(item.get("kind", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or name in names:
            raise Phase0ConfigurationError("Fixture names must be non-empty and unique")
        if kind not in REQUIRED_FIXTURE_KINDS:
            raise Phase0ConfigurationError(f"Unknown fixture kind: {kind or '<empty>'}")
        if "readable" in item and not isinstance(item["readable"], bool):
            raise Phase0ConfigurationError(f"Fixture {name} readable must be boolean")
        if "required" in item and not isinstance(item["required"], bool):
            raise Phase0ConfigurationError(f"Fixture {name} required must be boolean")
        markers = item.get("markers", [])
        if not isinstance(markers, list) or any(not isinstance(marker, str) or not marker for marker in markers):
            raise Phase0ConfigurationError(f"Fixture {name} markers must be non-empty strings")
        expected_min = item.get("expected_min", {})
        if not isinstance(expected_min, dict) or any(
            not isinstance(key, str) or not isinstance(value, int) or value < 0
            for key, value in expected_min.items()
        ):
            raise Phase0ConfigurationError(f"Fixture {name} has invalid expected_min")
        fixture = FixtureSpec(
            name=name,
            kind=kind,
            url=url,
            readable=bool(item.get("readable", True)),
            required=bool(item.get("required", True)),
            markers=tuple(markers),
            end_marker=str(item.get("end_marker", "")),
            expected_min=expected_min,
        )
        fixture.page_id
        fixtures.append(fixture)
        names.add(name)
    return Phase0Manifest(schema_version=1, fixtures=tuple(fixtures))


def load_attestation(path: Path | None, required_keys: frozenset[str], label: str) -> dict[str, Any]:
    if path is None:
        return {"status": "pending", "missing": sorted(required_keys), "observations": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or not isinstance(raw.get("observations"), Mapping):
        raise Phase0ConfigurationError(f"{label} must use schema_version 1 and contain observations")
    observations: dict[str, dict[str, Any]] = {}
    for key, value in raw["observations"].items():
        if key not in required_keys or not isinstance(value, Mapping):
            continue
        reference = str(value.get("reference", ""))
        observations[key] = {
            "passed": value.get("passed") is True,
            "source": str(value.get("source", "unspecified")),
            "reference_hash": stable_identifier(reference) if reference else "",
        }
    missing = sorted(key for key in required_keys if not observations.get(key, {}).get("passed"))
    return {"status": "pass" if not missing else "pending", "missing": missing, "observations": observations}


def manifest_preflight(manifest: Phase0Manifest) -> dict[str, Any]:
    present = {fixture.kind for fixture in manifest.fixtures}
    missing = sorted(REQUIRED_FIXTURE_KINDS - present)
    long_fixtures = [fixture for fixture in manifest.fixtures if fixture.kind == "long_content"]
    issues: list[str] = []
    if missing:
        issues.append("missing fixture kinds: " + ", ".join(missing))
    if not long_fixtures or not all(fixture.end_marker for fixture in long_fixtures):
        issues.append("long_content fixture requires an end_marker")
    if not any(not fixture.readable for fixture in manifest.fixtures):
        issues.append("a negative-control unreadable fixture is required")
    return {
        "status": "pass" if not issues else "fail",
        "fixture_count": len(manifest.fixtures),
        "fixture_kinds": sorted(present),
        "issues": issues,
    }


def auth_config_from_env(mode: str, env: Mapping[str, str] | None = None) -> AuthConfig:
    values = os.environ if env is None else env
    endpoint = values.get("ROVO_MCP_URL", "https://mcp.atlassian.com/v1/mcp/authv2").strip()
    endpoint_parts = urllib.parse.urlsplit(endpoint)
    if endpoint_parts.scheme != "https" or endpoint_parts.hostname != "mcp.atlassian.com":
        raise Phase0ConfigurationError("ROVO_MCP_URL must be the approved HTTPS Atlassian MCP host")
    if endpoint_parts.path.rstrip("/").endswith("/sse"):
        raise Phase0ConfigurationError("The retired /sse endpoint is forbidden")
    allowed_sites = tuple(
        sorted(
            {
                validate_https_site_url("https://" + item.strip().lower().removeprefix("https://"))
                for item in values.get("ROVO_MCP_ALLOWED_SITES", "").split(",")
                if item.strip()
            }
        )
    )
    if not allowed_sites:
        raise Phase0ConfigurationError("ROVO_MCP_ALLOWED_SITES must contain at least one exact site host")
    if mode == "personal":
        email = values.get("ROVO_MCP_EMAIL", "")
        token = values.get("ROVO_MCP_API_TOKEN", "")
        if not email or not token:
            raise Phase0ConfigurationError("personal auth requires ROVO_MCP_EMAIL and ROVO_MCP_API_TOKEN")
        encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        authorization = "Basic " + encoded
    elif mode == "service_account":
        key = values.get("ROVO_MCP_API_KEY", "")
        if not key:
            raise Phase0ConfigurationError("service_account auth requires ROVO_MCP_API_KEY")
        authorization = "Bearer " + key
    else:
        raise Phase0ConfigurationError(f"Unsupported auth mode: {mode}")
    timeout = float(values.get("ROVO_MCP_READ_TIMEOUT", "120"))
    return AuthConfig(mode, endpoint, authorization, allowed_sites, timeout)


def rest_config_from_env(env: Mapping[str, str] | None = None) -> RestConfig:
    values = os.environ if env is None else env
    mode = values.get("CONFLUENCE_REST_AUTH_MODE", "").strip().lower()
    if mode == "basic":
        email = values.get("CONFLUENCE_REST_EMAIL", "")
        token = values.get("CONFLUENCE_REST_API_TOKEN", "")
        if not email or not token:
            raise Phase0ConfigurationError("REST Basic auth requires email and API token")
        encoded = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        authorization = "Basic " + encoded
    elif mode == "bearer":
        token = values.get("CONFLUENCE_REST_BEARER_TOKEN", "")
        if not token:
            raise Phase0ConfigurationError("REST Bearer auth requires CONFLUENCE_REST_BEARER_TOKEN")
        authorization = "Bearer " + token
    else:
        raise Phase0ConfigurationError("CONFLUENCE_REST_AUTH_MODE must be basic or bearer")
    return RestConfig(mode, authorization, float(values.get("CONFLUENCE_REST_TIMEOUT", "60")))


def object_to_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return {str(key): object_to_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [object_to_json(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def walk_json(value: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    yield path, None, value
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, str(key), child
            yield from walk_json(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(child, f"{path}[{index}]")


def _looks_like_markdown(text: str) -> bool:
    return bool(text.strip()) and (
        "\n" in text
        or text.lstrip().startswith(("#", "```", "|", "- ", "* "))
        or len(text) >= 200
    )


def markdown_candidates_from_result(result: Any) -> tuple[list[MarkdownCandidate], dict[str, Any]]:
    dumped = object_to_json(result)
    structured = dumped.get("structuredContent") or dumped.get("structured_content") if isinstance(dumped, dict) else None
    content = dumped.get("content", []) if isinstance(dumped, dict) else []
    candidates: list[MarkdownCandidate] = []

    if structured is not None:
        for path, key, value in walk_json(structured, "$.structuredContent"):
            if isinstance(value, str) and key and key.lower() in _MARKDOWN_KEY_NAMES and _looks_like_markdown(value):
                candidates.append(MarkdownCandidate(path, value))

    for index, block in enumerate(content if isinstance(content, list) else []):
        if not isinstance(block, Mapping) or block.get("type") != "text" or not isinstance(block.get("text"), str):
            continue
        text = block["text"]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            if _looks_like_markdown(text):
                candidates.append(MarkdownCandidate(f"$.content[{index}].text", text))
            continue
        for path, key, value in walk_json(parsed, f"$.content[{index}].text(json)"):
            if isinstance(value, str) and key and key.lower() in _MARKDOWN_KEY_NAMES and _looks_like_markdown(value):
                candidates.append(MarkdownCandidate(path, value))

    unique: dict[tuple[str, str], MarkdownCandidate] = {}
    for candidate in candidates:
        unique[(candidate.location, sha256_text(candidate.text))] = candidate
    candidates = list(unique.values())
    envelope = {
        "is_error": bool(dumped.get("isError") or dumped.get("is_error")) if isinstance(dumped, dict) else False,
        "structured_content_present": structured is not None,
        "content_block_types": [block.get("type", "unknown") for block in content if isinstance(block, Mapping)],
        "markdown_candidates": [candidate.summary() for candidate in candidates],
    }
    return candidates, envelope


def choose_authoritative_markdown(candidates: Sequence[MarkdownCandidate]) -> MarkdownCandidate:
    if not candidates:
        raise Phase0ResponseError("No Markdown candidate found in the MCP response")
    by_hash: dict[str, list[MarkdownCandidate]] = {}
    for candidate in candidates:
        by_hash.setdefault(sha256_text(candidate.text), []).append(candidate)
    if len(by_hash) != 1:
        locations = sorted(candidate.location for candidate in candidates)
        raise Phase0ResponseError("Ambiguous Markdown candidates at: " + ", ".join(locations))
    structured = [candidate for candidate in candidates if candidate.location.startswith("$.structuredContent")]
    return structured[0] if structured else candidates[0]


def truncation_evidence(result: Any) -> dict[str, Any]:
    dumped = object_to_json(result)
    signals: list[dict[str, Any]] = []
    cursors: list[dict[str, str]] = []
    for path, key, value in walk_json(dumped):
        normalized = (key or "").replace("_", "").lower()
        if normalized in {"truncated", "hasmore"} and isinstance(value, bool):
            signals.append({"path": path, "value": value})
        elif normalized == "stopreason" and isinstance(value, str):
            signals.append({"path": path, "value": value})
        elif normalized in _CURSOR_NAMES and isinstance(value, str) and value:
            cursors.append({"path": path, "value_hash": stable_identifier(value), "raw": value})
    truncated = any(item["value"] is True for item in signals if isinstance(item["value"], bool))
    truncated = truncated or any(
        isinstance(item["value"], str) and item["value"].strip().lower() not in _COMPLETED_STOP_REASONS
        for item in signals
    )
    return {
        "truncated": truncated,
        "signals": signals,
        "cursors": [{"path": item["path"], "value_hash": item["value_hash"]} for item in cursors],
        "cursor_values": [item["raw"] for item in cursors],
    }


def extract_page_version(result: Any) -> int | None:
    dumped = object_to_json(result)
    versions: set[int] = set()
    for _, key, value in walk_json(dumped):
        if (key or "").lower() != "version":
            continue
        if isinstance(value, int) and not isinstance(value, bool):
            versions.add(value)
        elif isinstance(value, Mapping):
            number = value.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                versions.add(number)
    if len(versions) > 1:
        raise Phase0ResponseError("MCP response contains conflicting page versions")
    return next(iter(versions)) if versions else None


def validate_same_page_version(rovo_version: int | None, rest_version: int | None) -> list[str]:
    if rovo_version is None:
        return ["Rovo page version missing; cannot prove same-version REST comparison"]
    if rest_version != rovo_version:
        return ["Rovo and REST page versions differ"]
    return []


def ensure_no_running_event_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise Phase0ConfigurationError("A synchronous Phase 0 entry point cannot run inside an active event loop")


def markdown_inventory(markdown: str, fixture: FixtureSpec) -> dict[str, Any]:
    fence_lines = re.findall(r"(?m)^\s*(```+|~~~+)", markdown)
    headings = re.findall(r"(?m)^\s{0,3}#{1,6}\s+\S", markdown)
    table_delimiters = re.findall(r"(?m)^\s*\|?\s*:?-{3,}", markdown)
    tasks = re.findall(r"(?mi)^\s*[-*+]\s+\[[ xX]\]\s+", markdown)
    links = re.findall(r"!?\[[^\]]*\]\([^\)]+\)", markdown)
    present_markers = [marker for marker in fixture.markers if marker in markdown]
    return {
        "char_count": len(markdown),
        "byte_count": len(markdown.encode("utf-8")),
        "sha256": sha256_text(markdown),
        "heading_count": len(headings),
        "table_count": len(table_delimiters),
        "code_fence_line_count": len(fence_lines),
        "unclosed_fence_indicator": len(fence_lines) % 2 == 1,
        "task_count": len(tasks),
        "link_count": len(links),
        "marker_count": len(present_markers),
        "expected_marker_count": len(fixture.markers),
        "end_marker_present": bool(fixture.end_marker and fixture.end_marker in markdown),
    }


def validate_inventory(inventory: Mapping[str, Any], fixture: FixtureSpec) -> list[str]:
    failures = []
    for key, minimum in fixture.expected_min.items():
        actual = inventory.get(key)
        if not isinstance(actual, int) or actual < minimum:
            failures.append(f"{key} expected >= {minimum}, got {actual!r}")
    if fixture.markers and inventory.get("marker_count") != inventory.get("expected_marker_count"):
        failures.append("one or more controlled markers are missing")
    if fixture.kind == "long_content":
        if int(inventory.get("char_count", 0)) <= 20_000:
            failures.append("long_content fixture did not exceed 20,000 characters")
        if not inventory.get("end_marker_present"):
            failures.append("long_content end marker is missing")
    return failures


def extract_resources(result: Any) -> list[dict[str, str]]:
    dumped = object_to_json(result)
    roots: list[Any] = []
    if isinstance(dumped, dict):
        if dumped.get("structuredContent") is not None:
            roots.append(dumped["structuredContent"])
        for block in dumped.get("content", []):
            if isinstance(block, Mapping) and block.get("type") == "text" and isinstance(block.get("text"), str):
                try:
                    roots.append(json.loads(block["text"]))
                except json.JSONDecodeError:
                    pass
    resources: dict[tuple[str, str], dict[str, str]] = {}
    for root in roots:
        for _, _, node in walk_json(root):
            if not isinstance(node, Mapping):
                continue
            url = node.get("url") or node.get("siteUrl")
            cloud_id = node.get("id") or node.get("cloudId")
            if isinstance(url, str) and isinstance(cloud_id, str):
                try:
                    host = validate_https_site_url(url)
                except Phase0ConfigurationError:
                    continue
                resources[(host, cloud_id)] = {"host": host, "cloud_id": cloud_id}
    return list(resources.values())


def select_cloud_id(resources: Sequence[Mapping[str, str]], host: str) -> str:
    matches = {item["cloud_id"] for item in resources if item.get("host") == host}
    if len(matches) != 1:
        raise Phase0CapabilityError(f"Expected one accessible resource for {host}; found {len(matches)}")
    return next(iter(matches))


def _tool_argument_names(schema: Mapping[str, Any]) -> set[str]:
    properties = schema.get("properties", {})
    return set(properties) if isinstance(properties, Mapping) else set()


def validate_required_tools(tool_names: Iterable[str]) -> None:
    missing = sorted(REQUIRED_TOOLS - set(tool_names))
    if missing:
        raise Phase0CapabilityError("Missing required tools: " + ", ".join(missing))


def build_page_arguments(schema: Mapping[str, Any], cloud_id: str, page_id: str, cursor: str = "") -> dict[str, Any]:
    names = _tool_argument_names(schema)
    if not {"cloudId", "pageId"}.issubset(names):
        raise Phase0CapabilityError("getConfluencePage schema must expose cloudId and pageId")
    arguments: dict[str, Any] = {"cloudId": cloud_id, "pageId": page_id}
    if cursor:
        for candidate in ("cursor", "continuationToken", "next"):
            if candidate in names:
                arguments[candidate] = cursor
                break
        else:
            raise Phase0TruncationError("Response exposes continuation but tool schema has no continuation argument")
    return arguments


def classify_exception(exc: BaseException) -> str:
    text = str(exc).lower()
    if "401" in text or "unauth" in text or "token" in text and "expired" in text:
        return "authentication"
    if "403" in text or "forbidden" in text or "permission" in text:
        return "authorization"
    if "404" in text or "not found" in text:
        return "not_found_or_invisible"
    if "429" in text or "rate limit" in text:
        return "rate_limit"
    if "timeout" in text or "disconnect" in text or "5xx" in text:
        return "transport"
    if isinstance(exc, Phase0CapabilityError):
        return "capability"
    if isinstance(exc, Phase0TruncationError):
        return "truncation"
    if isinstance(exc, Phase0ResponseError):
        return "response_schema"
    return "unknown"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def fetch_rest_storage(fixture: FixtureSpec, config: RestConfig) -> dict[str, Any]:
    endpoint = f"https://{fixture.site_host}/wiki/api/v2/pages/{fixture.page_id}?body-format=storage"
    request = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json", "Authorization": config.authorization},
        method="GET",
    )
    context = ssl.create_default_context()
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))
    try:
        with opener.open(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise Phase0ResponseError(f"REST HTTP {exc.code}") from exc
    page_id = str(payload.get("id", ""))
    version = payload.get("version", {}).get("number") if isinstance(payload.get("version"), Mapping) else None
    storage = payload.get("body", {}).get("storage") if isinstance(payload.get("body"), Mapping) else None
    value = storage.get("value") if isinstance(storage, Mapping) else None
    if page_id != fixture.page_id or not isinstance(value, str):
        raise Phase0ResponseError("REST storage response has an incompatible page/body schema")
    return {"page_id": page_id, "version": version, "storage_html": value}


def storage_inventory(storage_html: str, fixture: FixtureSpec) -> dict[str, Any]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - dependency preflight handles this in real runs
        raise Phase0ConfigurationError("beautifulsoup4 is required for REST storage inventory") from exc
    soup = BeautifulSoup(storage_html, "lxml")
    tables = soup.find_all("table")
    macros = soup.find_all(lambda tag: getattr(tag, "name", "") in {"ac:structured-macro", "structured-macro"})
    task_nodes = soup.find_all(lambda tag: "task" in getattr(tag, "name", "").lower())
    code_nodes = soup.find_all(["pre", "code"])
    marker_text = soup.get_text(" ", strip=True)
    return {
        "char_count": len(storage_html),
        "byte_count": len(storage_html.encode("utf-8")),
        "sha256": sha256_text(storage_html),
        "table_count": len(tables),
        "merged_cell_count": len(soup.select("[rowspan], [colspan]")),
        "nested_table_count": sum(1 for table in tables if table.find_parent("table") is not None),
        "macro_count": len(macros),
        "task_node_count": len(task_nodes),
        "code_node_count": len(code_nodes),
        "marker_count": sum(marker in marker_text for marker in fixture.markers),
        "expected_marker_count": len(fixture.markers),
        "end_marker_present": bool(fixture.end_marker and fixture.end_marker in marker_text),
    }


def _redacted_tool_schema(tool: Any) -> dict[str, Any]:
    dumped = object_to_json(tool)
    return {
        "name": dumped.get("name"),
        "description_sha256": sha256_text(str(dumped.get("description", ""))),
        "input_schema": dumped.get("inputSchema") or dumped.get("input_schema") or {},
    }


async def _read_fixture(
    client: Any,
    fixture: FixtureSpec,
    cloud_id: str,
    page_schema: Mapping[str, Any],
    max_pages: int,
    max_total_bytes: int,
) -> tuple[str, dict[str, Any], Any]:
    chunks: list[str] = []
    envelopes: list[dict[str, Any]] = []
    cursor = ""
    seen_cursors: set[str] = set()
    last_result: Any = None
    for page_number in range(1, max_pages + 1):
        arguments = build_page_arguments(page_schema, cloud_id, fixture.page_id, cursor)
        result = await client.call_tool("getConfluencePage", arguments)
        last_result = result
        candidates, envelope = markdown_candidates_from_result(result)
        envelope["page_number"] = page_number
        envelopes.append(envelope)
        if envelope["is_error"]:
            raise Phase0ResponseError("getConfluencePage returned a tool error")
        chunks.append(choose_authoritative_markdown(candidates).text)
        if sum(len(chunk.encode("utf-8")) for chunk in chunks) > max_total_bytes:
            raise Phase0TruncationError("MCP content exceeded max_total_bytes")
        truncation = truncation_evidence(result)
        cursor_values = truncation.pop("cursor_values")
        envelope["truncation"] = truncation
        if not cursor_values:
            if truncation["truncated"]:
                raise Phase0TruncationError("MCP response reports truncation without continuation")
            return "\n".join(chunks), {"pages": envelopes, "page_count": page_number}, last_result
        if len(set(cursor_values)) != 1:
            raise Phase0TruncationError("MCP response exposes ambiguous continuation cursors")
        cursor = cursor_values[0]
        cursor_hash = stable_identifier(cursor)
        if cursor_hash in seen_cursors:
            raise Phase0TruncationError("MCP continuation cursor loop detected")
        seen_cursors.add(cursor_hash)
    raise Phase0TruncationError("MCP content reached max_pages without a terminal page")


async def run_auth_mode(
    manifest: Phase0Manifest,
    config: AuthConfig,
    rest_config: RestConfig | None,
    max_pages: int,
    max_total_bytes: int,
) -> dict[str, Any]:
    try:
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise Phase0ConfigurationError("Install requirements-phase0.txt before a live Phase 0 run") from exc

    mode_evidence: dict[str, Any] = {
        "auth_mode": config.mode,
        "endpoint_path": urllib.parse.urlsplit(config.endpoint).path,
        "started_at": utc_now(),
        "status": "fail",
        "tools": [],
        "sites": [],
        "fixtures": [],
    }
    timeout = httpx2.Timeout(30.0, read=config.timeout_seconds)
    async with httpx2.AsyncClient(
        headers={"Authorization": config.authorization},
        timeout=timeout,
        follow_redirects=False,
    ) as http_client:
        transport = streamable_http_client(config.endpoint, http_client=http_client)
        async with Client(transport) as client:
            listed = await client.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            mode_evidence["tools"] = [_redacted_tool_schema(tool) for tool in listed.tools]
            validate_required_tools(tools)
            resources_result = await client.call_tool("getAccessibleAtlassianResources", {})
            if bool(getattr(resources_result, "is_error", False)):
                raise Phase0ResponseError("getAccessibleAtlassianResources returned a tool error")
            resources = extract_resources(resources_result)
            mode_evidence["sites"] = [
                {"host": item["host"], "cloud_id_hash": stable_identifier(item["cloud_id"])} for item in resources
            ]
            page_schema = object_to_json(tools["getConfluencePage"]).get("inputSchema") or object_to_json(
                tools["getConfluencePage"]
            ).get("input_schema", {})
            for fixture in manifest.fixtures:
                fixture_evidence: dict[str, Any] = {
                    "name": fixture.name,
                    "kind": fixture.kind,
                    "required": fixture.required,
                    "expected_readable": fixture.readable,
                    "site_host": fixture.site_host,
                    "page_id_hash": stable_identifier(fixture.page_id),
                    "status": "fail",
                }
                try:
                    cloud_id = select_cloud_id(resources, fixture.site_host)
                    markdown, envelope, last_result = await _read_fixture(
                        client, fixture, cloud_id, page_schema, max_pages, max_total_bytes
                    )
                    if not fixture.readable:
                        raise Phase0ResponseError("Negative-control page was unexpectedly readable")
                    inventory = markdown_inventory(markdown, fixture)
                    failures = validate_inventory(inventory, fixture)
                    rovo_version = extract_page_version(last_result)
                    fixture_evidence.update(
                        {"rovo": {"envelope": envelope, "inventory": inventory, "version": rovo_version}}
                    )
                    if rest_config is not None:
                        rest = await asyncio.to_thread(fetch_rest_storage, fixture, rest_config)
                        rest_inventory = storage_inventory(rest["storage_html"], fixture)
                        fixture_evidence["rest"] = {
                            "version": rest["version"],
                            "inventory": rest_inventory,
                        }
                        failures.extend(validate_same_page_version(rovo_version, rest["version"]))
                        if fixture.markers and rest_inventory["marker_count"] != rest_inventory["expected_marker_count"]:
                            failures.append("REST storage is missing one or more controlled markers")
                    fixture_evidence["failures"] = failures
                    fixture_evidence["status"] = "pass" if not failures else "fail"
                except Exception as exc:  # each fixture must leave classified evidence
                    category = classify_exception(exc)
                    if not fixture.readable and category in {"authorization", "not_found_or_invisible", "response_schema"}:
                        fixture_evidence.update({"status": "pass", "observed_error_category": category})
                    else:
                        fixture_evidence.update(
                            {
                                "status": "fail",
                                "observed_error_category": category,
                                "exception_type": type(exc).__name__,
                            }
                        )
                mode_evidence["fixtures"].append(fixture_evidence)
    required = [item for item in mode_evidence["fixtures"] if item["required"]]
    mode_evidence["status"] = "pass" if required and all(item["status"] == "pass" for item in required) else "fail"
    mode_evidence["finished_at"] = utc_now()
    return mode_evidence


def build_pending_evidence(
    manifest: Phase0Manifest,
    modes: Sequence[str],
    reasons: Sequence[str],
    admin_attestation: Mapping[str, Any] | None = None,
    failure_observations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": 0,
        "generated_at": utc_now(),
        "sdk_pin": "mcp==2.1.1",
        "status": "pending",
        "preflight": manifest_preflight(manifest),
        "requested_auth_modes": list(modes),
        "pending_reasons": list(reasons),
        "admin_checklist": admin_attestation or {"status": "pending"},
        "failure_matrix": failure_observations or {"status": "pending"},
    }


async def run_phase0(
    manifest: Phase0Manifest,
    modes: Sequence[str],
    include_rest: bool,
    max_pages: int,
    max_total_bytes: int,
    admin_attestation: Mapping[str, Any],
    failure_observations: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    preflight = manifest_preflight(manifest)
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "phase": 0,
        "generated_at": utc_now(),
        "sdk_pin": "mcp==2.1.1",
        "status": "fail",
        "preflight": preflight,
        "auth_runs": [],
        "admin_checklist": admin_attestation,
        "failure_matrix": failure_observations,
    }
    if preflight["status"] != "pass":
        return evidence
    rest_config = rest_config_from_env(env) if include_rest else None
    for mode in modes:
        try:
            config = auth_config_from_env(mode, env)
            auth_run = await run_auth_mode(manifest, config, rest_config, max_pages, max_total_bytes)
        except Exception as exc:
            auth_run = {
                "auth_mode": mode,
                "status": "fail",
                "error_category": classify_exception(exc),
                "exception_type": type(exc).__name__,
            }
        evidence["auth_runs"].append(auth_run)
    technical_pass = set(modes) == {"personal", "service_account"} and all(
        item.get("status") == "pass" for item in evidence["auth_runs"]
    )
    attestations_pass = admin_attestation.get("status") == "pass" and failure_observations.get("status") == "pass"
    evidence["status"] = "pass" if technical_pass and attestations_pass else "pending" if technical_pass else "fail"
    return evidence


def write_evidence(path: Path, evidence: Mapping[str, Any]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for secret_name in SECRET_ENV_NAMES:
        secret = os.environ.get(secret_name, "")
        if secret and secret in serialized:
            raise Phase0Error(f"Refusing to write evidence containing {secret_name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)
