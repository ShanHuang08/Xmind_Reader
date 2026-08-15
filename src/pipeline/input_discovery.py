"""Case-insensitive input discovery for the new-vendor pipeline."""

from __future__ import annotations

import datetime as dt
from pathlib import Path


def find_case_insensitive(root: Path, name: str) -> list[Path]:
    wanted = name.casefold()
    ignored = {".git", "output", "__pycache__"}
    matches = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name.casefold() != wanted:
            continue
        if any(part.casefold() in ignored for part in path.relative_to(root).parts):
            continue
        matches.append(path)
    return sorted(matches)


def created_time(path: Path) -> str:
    stat = path.stat()
    timestamp = getattr(stat, "st_birthtime", stat.st_ctime)
    return dt.datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def choose_match(root: Path, name: str) -> Path:
    matches = find_case_insensitive(root, name)
    if not matches:
        raise FileNotFoundError(f"Cannot find {name!r} below {root}")
    if len(matches) == 1:
        return matches[0]

    print(f"Multiple files match {name!r}. Choose one:")
    for index, path in enumerate(matches, start=1):
        print(f"  {index}. {path} (created: {created_time(path)})")
    answer = input(f"Enter 1-{len(matches)}: ").strip()
    try:
        selected = int(answer)
    except ValueError as exc:
        raise RuntimeError(f"Invalid selection {answer!r}; enter a number.") from exc
    if not 1 <= selected <= len(matches):
        raise RuntimeError(f"Invalid selection {selected}; choose a number from 1 to {len(matches)}.")
    return matches[selected - 1]


def find_vendor_document(root: Path, vendor: str) -> Path:
    for suffix in (".doc", ".docx"):
        matches = find_case_insensitive(root, f"Vendor_{vendor}{suffix}")
        if matches:
            return choose_match(root, f"Vendor_{vendor}{suffix}")
    raise FileNotFoundError(f"Cannot find Vendor_{vendor}.doc or Vendor_{vendor}.docx below {root}")
