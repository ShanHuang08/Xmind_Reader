"""Export vendor document details into Codex-friendly files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_vendor_detail(detail: dict[str, Any], output_root: Path) -> dict[str, Path]:
    vendor_dir = Path(output_root) / detail["vendor"]
    vendor_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        "api_summary": vendor_dir / "api_summary.md",
        "endpoints": vendor_dir / "endpoints.json",
        "error_codes": vendor_dir / "error_codes.json",
        "capability_profile": vendor_dir / "capability_profile.json",
        "vendor_master_checklist": vendor_dir / "vendor_master_checklist.json",
        "game_codes": vendor_dir / "game_codes.json",
        "source_meta": vendor_dir / "source_meta.json",
        "raw_doc": vendor_dir / "raw_doc.json",
    }
    paths["api_summary"].write_text(_render_summary(detail), encoding="utf-8")
    _write_json(detail.get("endpoints", []), paths["endpoints"])
    _write_json(detail.get("error_codes", []), paths["error_codes"])
    _write_json(detail.get("capability_profile", {}), paths["capability_profile"])
    _write_json(detail.get("vendor_master_checklist", []), paths["vendor_master_checklist"])
    _write_json(detail.get("game_codes", []), paths["game_codes"])
    _write_json(detail.get("source_meta", {}), paths["source_meta"])
    _write_json(_raw_payload(detail), paths["raw_doc"])
    return paths


def _render_summary(detail: dict[str, Any]) -> str:
    lines = [
        f"# {detail['vendor']} API Summary",
        "",
        f"Source: {detail.get('source_file', '')}",
        f"Title: {detail.get('title', '')}",
        "",
        "## Capability Profile",
        "",
    ]
    supports = detail.get("capability_profile", {}).get("supports", {})
    supports_source = detail.get("capability_profile", {}).get("supports_source", {})
    for key, value in sorted(supports.items()):
        source = supports_source.get(key, "unknown")
        lines.append(f"- {key}: {value} ({source})")

    checklist = detail.get("vendor_master_checklist", [])
    if checklist:
        lines.extend(["", "## Vendor Master Check List", ""])
        lines.append("| Name | Enabled | Capability | Description | Remark |")
        lines.append("|---|---:|---|---|---|")
        for item in checklist:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(item.get("name", "")),
                        str(item.get("enabled", "")),
                        str(item.get("capability_key", "")),
                        str(item.get("description", "")),
                        str(item.get("remark", "")),
                    ]
                )
                + " |"
            )

    lines.extend(["", "## Endpoints", ""])
    for endpoint in detail.get("endpoints", []):
        methods = ", ".join(endpoint.get("methods", [])) or "unknown"
        keywords = ", ".join(endpoint.get("keywords", [])) or "none"
        lines.append(f"- `{endpoint['endpoint']}` | method: {methods} | section: {endpoint.get('section', '')} | keywords: {keywords}")

    lines.extend(["", "## Error Codes", ""])
    for item in detail.get("error_codes", [])[:80]:
        lines.append(f"- `{item['code']}`: {item.get('context', '')[:240]}")

    lines.extend(["", "## Sections", ""])
    for section in detail.get("sections", [])[:120]:
        lines.append(f"### {section.get('title', '')}")
        for paragraph in section.get("content", [])[:12]:
            lines.append(f"- {paragraph}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _raw_payload(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "vendor": detail.get("vendor"),
        "source_file": detail.get("source_file"),
        "title": detail.get("title"),
        "sections": detail.get("sections", []),
        "tables": detail.get("tables", []),
        "game_codes": detail.get("game_codes", []),
        "tables_detailed": detail.get("tables_detailed", []),
        "links": detail.get("links", []),
    }


def _write_json(data: Any, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
