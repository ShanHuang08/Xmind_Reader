"""Canonical parsing only; never attempts vendor-specific extraction."""
from pathlib import Path
import re

from MarkItDown_reader.contracts import MARKER, SCHEMA, digest, require, strict_json, validate_document
from MarkItDown_reader.markdown_renderer import render_canonical_markdown

VERSION = "1"


def declares_canonical(text: str) -> bool:
    return text.lstrip("\ufeff \r\n").startswith(MARKER)


def parse_canonical(text: str) -> dict:
    require(text.startswith(f"{MARKER}{SCHEMA} -->\n"), "Unsupported or damaged canonical declaration")
    match = re.search(r"^(`{3,})json\n", text, re.M)
    require(match is not None, "Missing document contract")
    end = text.find("\n" + match[1] + "\n", match.end())
    require(end >= 0, "Unclosed document contract")
    doc = strict_json(text[match.end():end])
    validate_document(doc)
    require(text == render_canonical_markdown(doc), "Canonical reading view differs from contract; edit through normalization")
    return doc


def read_canonical_markdown(path: Path, expected_hash: str | None = None) -> dict:
    raw = path.read_bytes()
    if expected_hash is not None:
        require(digest(raw) == expected_hash, "Canonical file hash mismatch")
    return parse_canonical(raw.decode("utf-8"))
