"""Read XMind files and preserve raw topic data."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

LOGGER = logging.getLogger(__name__)


class XMindParseError(Exception):
    """Raised when an XMind file cannot be opened or parsed."""


@dataclass
class ParseStats:
    sheet_count: int = 0
    topic_count: int = 0
    test_case_count: int = 0
    fields_extracted: set[str] | None = None
    missing_or_unsupported: set[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet_count": self.sheet_count,
            "topic_count": self.topic_count,
            "test_case_count": self.test_case_count,
            "fields_extracted": sorted(self.fields_extracted or set()),
            "missing_or_unsupported": sorted(self.missing_or_unsupported or set()),
        }


def parse_xmind_file(path: Path) -> dict[str, Any]:
    """Parse a .xmind file into raw sheets and normalized source cases."""
    path = Path(path)
    if not path.exists():
        raise XMindParseError(f"File does not exist: {path}")
    if path.suffix.lower() != ".xmind":
        raise XMindParseError(f"Unsupported file extension: {path.suffix}")

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "content.json" in names:
                sheets = _parse_content_json(archive)
                source_format = "content.json"
            elif "content.xml" in names:
                sheets = _parse_content_xml(archive)
                source_format = "content.xml"
            else:
                raise XMindParseError("No content.json or content.xml found in archive.")
            metadata = _read_json_if_present(archive, "metadata.json")
            manifest = _read_json_if_present(archive, "manifest.json")
    except zipfile.BadZipFile as exc:
        raise XMindParseError(f"Unreadable XMind zip archive: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise XMindParseError(f"Invalid JSON inside XMind archive: {exc}") from exc
    except ElementTree.ParseError as exc:
        raise XMindParseError(f"Invalid XML inside XMind archive: {exc}") from exc

    topic_count = sum(_count_topics(sheet["root_topic"]) for sheet in sheets)
    source_cases = _extract_source_cases(sheets)
    stats = ParseStats(
        sheet_count=len(sheets),
        topic_count=topic_count,
        test_case_count=len(source_cases),
        fields_extracted=_fields_present(sheets, source_cases),
        missing_or_unsupported=_missing_or_unsupported(sheets),
    )

    LOGGER.info(
        "Parsed %s: %s sheets, %s topics, %s test cases",
        path.name,
        stats.sheet_count,
        stats.topic_count,
        stats.test_case_count,
    )

    return {
        "source_file": path.name,
        "source_path": str(path),
        "source_format": source_format,
        "metadata": metadata,
        "manifest": manifest,
        "stats": stats.as_dict(),
        "sheets": sheets,
        "source_cases": source_cases,
    }


def walk_topics(topic: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield topic
    for child in topic.get("children", []):
        yield from walk_topics(child)


def _parse_content_json(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    content = json.loads(archive.read("content.json").decode("utf-8"))
    sheets = []
    for index, sheet in enumerate(content):
        root = _topic_from_json(sheet.get("rootTopic", {}), order=0, path=[])
        sheets.append(
            {
                "id": sheet.get("id"),
                "title": sheet.get("title") or "Missing Sheet Title",
                "index": index,
                "class": sheet.get("class"),
                "root_topic": root,
            }
        )
    return sheets


def _topic_from_json(topic: dict[str, Any], order: int, path: list[str]) -> dict[str, Any]:
    title = _clean_text(topic.get("title", ""))
    children = topic.get("children", {}).get("attached", []) or []
    current_path = path + ([title] if title else [])
    parsed = _drop_empty(
        {
            "id": topic.get("id"),
            "title": title,
            "order": order,
            "path": current_path,
            "markers": _extract_markers(topic),
            "notes": _extract_notes(topic),
            "labels": _extract_labels(topic),
            "hyperlinks": _extract_hyperlinks(topic),
            "children": [],
        }
    )
    parsed["children"] = [
        _topic_from_json(child, child_index, current_path)
        for child_index, child in enumerate(children, start=1)
    ]
    return parsed


def _parse_content_xml(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(archive.read("content.xml"))
    ns = {"x": "urn:xmind:xmap:xmlns:content:2.0"}
    sheets = []
    for index, sheet in enumerate(root.findall("x:sheet", ns)):
        topic = sheet.find("x:topic", ns)
        title = sheet.findtext("x:title", default="", namespaces=ns)
        sheets.append(
            {
                "id": sheet.get("id"),
                "title": _clean_text(title) or "Missing Sheet Title",
                "index": index,
                "class": "sheet",
                "root_topic": _topic_from_xml(topic, 0, [], ns) if topic is not None else {},
            }
        )
    return sheets


def _topic_from_xml(
    topic: ElementTree.Element, order: int, path: list[str], ns: dict[str, str]
) -> dict[str, Any]:
    title = _clean_text(topic.findtext("x:title", default="", namespaces=ns))
    current_path = path + ([title] if title else [])
    children = topic.findall("x:children/x:topics[@type='attached']/x:topic", ns)
    hyperlink = topic.get("{http://www.w3.org/1999/xlink}href") or topic.get("href")
    parsed = _drop_empty(
        {
            "id": topic.get("id"),
            "title": title,
            "order": order,
            "path": current_path,
            "markers": [
                item.get("marker-id")
                for item in topic.findall("x:marker-refs/x:marker-ref", ns)
                if item.get("marker-id")
            ],
            "notes": [
                _clean_text(item.text or "")
                for item in topic.findall("x:notes/x:plain", ns)
                if _clean_text(item.text or "")
            ],
            "labels": [
                _clean_text(item.text or "")
                for item in topic.findall("x:labels/x:label", ns)
                if _clean_text(item.text or "")
            ],
            "hyperlinks": [hyperlink] if hyperlink else [],
            "children": [],
        }
    )
    parsed["children"] = [
        _topic_from_xml(child, child_index, current_path, ns)
        for child_index, child in enumerate(children, start=1)
    ]
    return parsed


def _extract_source_cases(sheets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for sheet in sheets:
        for topic in walk_topics(sheet["root_topic"]):
            if _is_case_topic(topic):
                cases.append(_case_from_topic(sheet, topic))
    return cases


def _case_from_topic(sheet: dict[str, Any], topic: dict[str, Any]) -> dict[str, Any]:
    details: dict[str, str] = {}
    steps: list[dict[str, str]] = []
    for child in topic.get("children", []):
        title = child.get("title", "")
        key, value = split_prefixed_title(title)
        if key == "步骤描述" or title.strip() == "步骤描述":
            steps = _extract_steps(child)
        elif key:
            details[key] = value

    case_name = strip_prefix(topic.get("title", ""), ("case：", "case:", "用例：", "用例:"))
    module_path_parts = topic.get("path", [])[:-1]
    if module_path_parts and module_path_parts[0] == sheet["root_topic"].get("title"):
        module_path_parts = module_path_parts[1:]

    labels = list(topic.get("labels", []))
    notes = _public_notes(topic.get("notes", []))
    if details.get("标签"):
        labels.append(details["标签"])

    visible_case_id = (
        details.get("merge_key", "")
        or details.get("case_key", "")
        or details.get("case_id", "")
        or details.get("ID", "")
    )
    stable_case_id = visible_case_id or _stable_case_id_from_topic(topic)

    return _drop_empty(
        {
            "source_file": "",
            "sheet": sheet.get("title"),
            "case_id": visible_case_id,
            "name": case_name,
            "preconditions": details.get("前置条件", ""),
            "module_path": " > ".join(module_path_parts),
            "module_title": details.get("所属模块", ""),
            "steps": steps,
            "labels": labels,
            "remarks": details.get("备注", ""),
            "priority": details.get("用例等级", ""),
            "stable_case_id": stable_case_id,
            "markers": topic.get("markers", []),
            "notes": notes,
            "hyperlinks": topic.get("hyperlinks", []),
            "raw_topic_id": topic.get("id"),
            "raw_path": topic.get("path", []),
        }
    )


def _extract_steps(step_root: dict[str, Any]) -> list[dict[str, str]]:
    steps = []
    for index, step_topic in enumerate(step_root.get("children", []), start=1):
        _, step_text = split_prefixed_title(step_topic.get("title", ""))
        step_text = step_text or step_topic.get("title", "")
        expected_parts = []
        for child in step_topic.get("children", []):
            key, value = split_prefixed_title(child.get("title", ""))
            expected_parts.append(value if key == "预期结果" else child.get("title", ""))
        steps.append(
            _drop_empty(
                {
                    "index": index,
                    "step": step_text,
                    "expected": "\n".join(part for part in expected_parts if part),
                    "raw_topic_id": step_topic.get("id"),
                }
            )
        )
    return steps


def split_prefixed_title(title: str) -> tuple[str, str]:
    match = re.match(r"^\s*([^：:]+)\s*[：:]\s*(.*)$", title or "", re.DOTALL)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip()


def strip_prefix(value: str, prefixes: tuple[str, ...]) -> str:
    text = (value or "").strip()
    lower = text.lower()
    for prefix in prefixes:
        if lower.startswith(prefix.lower()):
            return text[len(prefix) :].strip()
    return text


def _is_case_topic(topic: dict[str, Any]) -> bool:
    return (topic.get("title") or "").strip().lower().startswith(("case：", "case:"))


def _count_topics(topic: dict[str, Any]) -> int:
    return sum(1 for _ in walk_topics(topic)) if topic else 0


def _extract_markers(topic: dict[str, Any]) -> list[str]:
    refs = topic.get("markers") or topic.get("markerRefs") or []
    markers = []
    for ref in refs:
        if isinstance(ref, dict):
            marker_id = ref.get("markerId") or ref.get("marker-id") or ref.get("id")
            if marker_id:
                markers.append(marker_id)
        elif isinstance(ref, str):
            markers.append(ref)
    return markers


def _extract_notes(topic: dict[str, Any]) -> list[str]:
    notes = topic.get("notes")
    if not notes:
        return []
    if isinstance(notes, str):
        return [_clean_text(notes)]
    if isinstance(notes, dict):
        output = []
        for key in ("plain", "html", "content"):
            value = notes.get(key)
            if isinstance(value, str) and value.strip():
                output.append(_clean_text(value))
            elif isinstance(value, dict):
                content = value.get("content")
                if isinstance(content, str) and content.strip():
                    output.append(_clean_text(content))
        return output
    if isinstance(notes, list):
        return [_clean_text(str(item)) for item in notes if str(item).strip()]
    return []


def _extract_labels(topic: dict[str, Any]) -> list[str]:
    labels = topic.get("labels") or []
    if isinstance(labels, str):
        return [_clean_text(labels)]
    return [_clean_text(str(label)) for label in labels if str(label).strip()]


def _extract_hyperlinks(topic: dict[str, Any]) -> list[str]:
    links = []
    for key in ("href", "hyperlink", "hyperlinks"):
        value = topic.get(key)
        if isinstance(value, str) and value.strip():
            links.append(value.strip())
        elif isinstance(value, list):
            links.extend(str(item).strip() for item in value if str(item).strip())
    return links


def _read_json_if_present(archive: zipfile.ZipFile, name: str) -> dict[str, Any] | None:
    if name not in archive.namelist():
        return None
    return json.loads(archive.read(name).decode("utf-8"))


def _fields_present(sheets: list[dict[str, Any]], cases: list[dict[str, Any]]) -> set[str]:
    fields = {"sheets", "topics", "titles", "hierarchy", "order"}
    all_topics = [topic for sheet in sheets for topic in walk_topics(sheet["root_topic"])]
    for field in ("markers", "notes", "labels", "hyperlinks"):
        if any(topic.get(field) for topic in all_topics):
            fields.add(field)
    if cases:
        fields.update(
            {
                "test_case_name",
                "preconditions",
                "module",
                "steps",
                "expected_results",
                "remarks",
                "priority",
            }
        )
    if any(case.get("case_id") for case in cases):
        fields.add("case_id")
    if any(case.get("stable_case_id") for case in cases):
        fields.add("stable_case_id")
    return fields


def _missing_or_unsupported(sheets: list[dict[str, Any]]) -> set[str]:
    missing = set()
    all_topics = [topic for sheet in sheets for topic in walk_topics(sheet["root_topic"])]
    for field in ("notes", "labels", "hyperlinks"):
        if not any(topic.get(field) for topic in all_topics):
            missing.add(f"{field}: not present in sample or unsupported by file")
    return missing


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _stable_case_id_from_topic(topic: dict[str, Any]) -> str:
    return ""


def _public_notes(notes: Any) -> list[str]:
    if not isinstance(notes, list):
        return []
    return [str(note) for note in notes if str(note).strip()]


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in ("", None, [], {})}
