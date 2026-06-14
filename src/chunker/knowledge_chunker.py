"""Split compact knowledge into module and tag chunks."""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any


def chunk_knowledge(cases: list[dict[str, Any]]) -> dict[str, Any]:
    module_chunks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tag_chunks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        module_chunks[slugify(case.get("module", "unclassified"))].append(case)
        for tag in case.get("tags", ["unclassified"]):
            tag_chunks[slugify(tag)].append(case)

    duplicates = detect_duplicates(cases)
    return {
        "modules": dict(sorted(module_chunks.items())),
        "tags": dict(sorted(tag_chunks.items())),
        "duplicates": duplicates,
    }


def detect_duplicates(cases: list[dict[str, Any]], threshold: float = 0.92) -> list[dict[str, Any]]:
    """Detect highly similar cases without removing them."""
    signatures: list[tuple[str, str, str]] = []
    duplicates = []
    for case in cases:
        signature = _case_signature(case)
        duplicate_of = ""
        score = 0.0
        for previous_id, previous_signature, _ in signatures:
            ratio = SequenceMatcher(None, signature, previous_signature).ratio()
            if ratio >= threshold and ratio > score:
                duplicate_of = previous_id
                score = ratio
        if duplicate_of:
            case["duplicate_of"] = duplicate_of
            duplicates.append(
                {
                    "id": case.get("id"),
                    "duplicate_of": duplicate_of,
                    "similarity": round(score, 4),
                    "module": case.get("module"),
                    "scenario": case.get("scenario"),
                }
            )
        signatures.append((case.get("id", ""), signature, case.get("module", "")))
    return duplicates


def slugify(value: str) -> str:
    text = (value or "unclassified").strip().lower()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unclassified"


def _case_signature(case: dict[str, Any]) -> str:
    parts = [
        case.get("module", ""),
        case.get("scenario", ""),
        " ".join(case.get("steps", [])),
        " ".join(case.get("expected_results", [])),
    ]
    return re.sub(r"\s+", " ", " ".join(parts).lower()).strip()
