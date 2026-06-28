"""Fetch vendor API documentation from URLs."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class UrlReadError(RuntimeError):
    """Raised when a URL source cannot be fetched or parsed."""


@dataclass(frozen=True)
class UrlFetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    sha256: str
    fetch_method: str = "static"


def fetch_url(url: str, username: str = "", password: str = "", timeout: int = 30) -> UrlFetchResult:
    errors: list[str] = []
    for candidate_url in _candidate_urls(url):
        try:
            return _fetch_url_with_urllib(candidate_url, username, password, timeout)
        except UrlReadError as exc:
            errors.append(str(exc))
            if _should_try_next_url(exc):
                continue
            break

    if platform.system().lower() == "windows" and shutil.which("powershell"):
        try:
            return _fetch_url_with_powershell(url, username, password, timeout)
        except UrlReadError as exc:
            errors.append(str(exc))

    for candidate_url in _candidate_urls(url):
        try:
            return _fetch_url_with_playwright(candidate_url, timeout)
        except UrlReadError as exc:
            errors.append(f"browser fallback failed for {candidate_url}: {exc}")
            if _should_try_next_url(exc):
                continue
            break

    raise UrlReadError("; ".join(error for error in errors if error) or f"Failed to read {url}")


def _candidate_urls(url: str) -> list[str]:
    urls = [url]
    if not url.endswith("/"):
        urls.append(f"{url}/")
    return urls


def _should_try_next_url(error: Exception) -> bool:
    message = str(error)
    return "401" in message or "404" in message or "403" in message


def _fetch_url_with_urllib(url: str, username: str, password: str, timeout: int) -> UrlFetchResult:
    headers = {
        "User-Agent": "XMind-Reader-URL-Reader/1.0",
        "Accept": "text/html,application/json,application/yaml,text/yaml,text/plain,*/*",
    }
    if username or password:
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("content-type", "")
            encoding = response.headers.get_content_charset() or "utf-8"
            text = raw.decode(encoding, errors="replace")
            return UrlFetchResult(
                url=url,
                final_url=response.geturl(),
                status_code=getattr(response, "status", 200),
                content_type=content_type,
                text=text,
                sha256=hashlib.sha256(raw).hexdigest(),
                fetch_method="urllib",
            )
    except HTTPError as exc:
        raise UrlReadError(f"HTTP {exc.code} while reading {url}") from exc
    except URLError as exc:
        raise UrlReadError(f"Failed to read {url}: {exc.reason}") from exc


def _fetch_url_with_powershell(url: str, username: str, password: str, timeout: int) -> UrlFetchResult:
    urls = [url]
    if not url.endswith("/"):
        urls.append(f"{url}/")
    last_error = ""
    for candidate_url in urls:
        try:
            return _fetch_url_with_powershell_once(candidate_url, username, password, timeout)
        except UrlReadError as exc:
            last_error = str(exc)
            if "401" not in last_error:
                try:
                    return _fetch_url_with_playwright(candidate_url, timeout)
                except UrlReadError as browser_exc:
                    last_error = f"{last_error}; browser fallback failed: {browser_exc}"
                    break
    raise UrlReadError(last_error)


def _fetch_url_with_powershell_once(url: str, username: str, password: str, timeout: int) -> UrlFetchResult:
    with tempfile.TemporaryDirectory(prefix="url_reader_") as tmp:
        body_path = os.path.join(tmp, "body.bin")
        meta_path = os.path.join(tmp, "meta.json")
        env = dict(os.environ)
        env.update(
            {
                "URL_READER_URL": url,
                "URL_READER_USERNAME": username,
                "URL_READER_PASSWORD": password,
                "URL_READER_TIMEOUT": str(timeout),
                "URL_READER_BODY": body_path,
                "URL_READER_META": meta_path,
            }
        )
        script = r"""
$ErrorActionPreference = 'Stop'
$uri = $env:URL_READER_URL
$timeout = [int]$env:URL_READER_TIMEOUT
$headers = @{ 'User-Agent' = 'XMind-Reader-URL-Reader/1.0' }
$params = @{
  Uri = $uri
  UseBasicParsing = $true
  TimeoutSec = $timeout
  Headers = $headers
}
if ($env:URL_READER_USERNAME -or $env:URL_READER_PASSWORD) {
  $secure = ConvertTo-SecureString $env:URL_READER_PASSWORD -AsPlainText -Force
  $params.Credential = New-Object System.Management.Automation.PSCredential($env:URL_READER_USERNAME, $secure)
}
$response = Invoke-WebRequest @params
$encoding = [System.Text.Encoding]::UTF8
$bytes = $encoding.GetBytes([string]$response.Content)
[System.IO.File]::WriteAllBytes($env:URL_READER_BODY, $bytes)
$meta = @{
  status_code = [int]$response.StatusCode
  final_url = [string]$response.BaseResponse.ResponseUri
  content_type = [string]$response.Headers['Content-Type']
}
$meta | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $env:URL_READER_META
"""
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout + 10,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise UrlReadError(f"PowerShell failed to read {url}: {message}")
        raw = open(body_path, "rb").read()
        meta = json.loads(open(meta_path, "r", encoding="utf-8-sig").read())
        text = raw.decode("utf-8", errors="replace")
        return UrlFetchResult(
            url=url,
            final_url=meta.get("final_url") or url,
            status_code=int(meta.get("status_code") or 0),
            content_type=meta.get("content_type") or "",
            text=text,
            sha256=hashlib.sha256(raw).hexdigest(),
            fetch_method="powershell",
        )


def _fetch_url_with_playwright(url: str, timeout: int) -> UrlFetchResult:
    node_path = _bundled_node()
    node_modules = _bundled_node_modules()
    if not node_path or not node_modules:
        raise UrlReadError("Bundled Node.js or node_modules not found for browser fallback.")
    playwright_paths = _playwright_node_paths(node_modules)
    if not playwright_paths:
        raise UrlReadError("Playwright package is not available for browser fallback.")

    with tempfile.TemporaryDirectory(prefix="url_reader_browser_") as tmp:
        body_path = os.path.join(tmp, "body.html")
        meta_path = os.path.join(tmp, "meta.json")
        script_path = os.path.join(tmp, "fetch_url.js")
        script = r"""
const { chromium } = require("playwright");
const fs = require("fs");

(async () => {
  const url = process.env.URL_READER_URL;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ ignoreHTTPSErrors: true });
  const response = await page.goto(url, {
    waitUntil: "domcontentloaded",
    timeout: Number(process.env.URL_READER_TIMEOUT || 30) * 1000,
  });
  await page.waitForSelector("body", { timeout: 30000 });
  await page.waitForTimeout(5000);
  const html = await page.content();
  const text = await page.locator("body").innerText({ timeout: 30000 }).catch(() => "");
  fs.writeFileSync(process.env.URL_READER_BODY, html, "utf8");
  fs.writeFileSync(process.env.URL_READER_META, JSON.stringify({
    status_code: response ? response.status() : 0,
    final_url: page.url(),
    content_type: response ? (response.headers()["content-type"] || "text/html") : "text/html",
    text_length: text.length
  }));
  await browser.close();
})().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
"""
        open(script_path, "w", encoding="utf-8").write(script)
        env = dict(os.environ)
        env.update(
            {
                "NODE_OPTIONS": "--use-system-ca",
                "NODE_PATH": os.pathsep.join(str(path) for path in playwright_paths),
                "URL_READER_URL": url,
                "URL_READER_TIMEOUT": str(timeout),
                "URL_READER_BODY": body_path,
                "URL_READER_META": meta_path,
            }
        )
        completed = subprocess.run(
            [str(node_path), script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout + 45,
        )
        if completed.returncode != 0:
            raise UrlReadError((completed.stderr or completed.stdout or "").strip())
        raw = open(body_path, "rb").read()
        meta = json.loads(open(meta_path, "r", encoding="utf-8").read())
        text = raw.decode("utf-8", errors="replace")
        return UrlFetchResult(
            url=url,
            final_url=meta.get("final_url") or url,
            status_code=int(meta.get("status_code") or 0),
            content_type=meta.get("content_type") or "text/html",
            text=text,
            sha256=hashlib.sha256(raw).hexdigest(),
            fetch_method="playwright_browser_fallback",
        )


def _playwright_node_paths(node_modules: Path) -> list[Path]:
    paths = [node_modules]
    if (node_modules / "playwright").exists():
        return paths
    pnpm_dir = node_modules / ".pnpm"
    if pnpm_dir.exists():
        for package_dir in pnpm_dir.glob("playwright*@*/node_modules"):
            if (package_dir / "playwright").exists() or (package_dir / "playwright-core").exists():
                paths.append(package_dir)
        if len(paths) > 1:
            return paths
    return []


def _bundled_node() -> Path | None:
    home = Path.home()
    node_bin = home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin"
    for executable in ("node.exe", "node"):
        candidate = node_bin / executable
        if candidate.exists():
            return candidate
    resolved = shutil.which("node")
    return Path(resolved) if resolved else None


def _bundled_node_modules() -> Path | None:
    home = Path.home()
    candidates = [
        home / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "node_modules",
        Path.cwd() / "node_modules",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    resolved_node = shutil.which("node")
    if not resolved_node:
        return None
    node_modules = Path(resolved_node).resolve().parents[1] / "lib" / "node_modules"
    return node_modules if node_modules.exists() else None


def is_openapi_like(fetch_result: UrlFetchResult) -> bool:
    parsed = urlparse(fetch_result.final_url)
    path = parsed.path.lower()
    content_type = fetch_result.content_type.lower()
    if path.endswith((".json", ".yaml", ".yml")):
        return True
    if "application/json" in content_type or "yaml" in content_type:
        return True
    try:
        data = json.loads(fetch_result.text)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and ("openapi" in data or "swagger" in data or "paths" in data)


def load_openapi_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UrlReadError("URL content is not valid JSON. YAML OpenAPI is not supported yet.") from exc
    if not isinstance(data, dict):
        raise UrlReadError("OpenAPI source must be a JSON object.")
    return data
