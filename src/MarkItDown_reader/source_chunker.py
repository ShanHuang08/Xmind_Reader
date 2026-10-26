"""Lossless heading blocks with fence awareness, independent of endpoints."""
import re
from .contracts import digest

VERSION = "1"


def chunk_source(text: str) -> list[dict]:
    lines = text.splitlines()
    if not lines:
        return []
    starts = [0]
    fence = None
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = m[1]
            elif m[1][0] == fence[0] and len(m[1]) >= len(fence):
                fence = None
        elif fence is None and i and (
            re.match(r"^#{1,6}\s+", line)
            or (re.match(r"^\s*\d+(?:\.\d+)+\s+[A-Z][^\r\n]{1,100}?\s*$", line)
                and not re.search(r"\.{3,}", line))
            or _is_plain_api_heading(lines, i)
        ):
            starts.append(i)
    result = []
    for start, end in zip(starts, starts[1:] + [len(lines)]):
        result.append({"block_id": f"block_{start + 1}_{digest(chr(10).join(lines[start:end]))[:12]}",
                       "line_start": start + 1, "line_end": end})
    return result


def _is_plain_api_heading(lines: list[str], index: int) -> bool:
    """Recognize flattened PDF headings immediately preceding Request metadata."""
    title = lines[index].strip().strip("* ")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _/-]{0,79}", title):
        return False
    following = "\n".join(lines[index + 1:min(len(lines), index + 10)])
    if not re.search(r"(?im)^\s*Request\s*:?\s*$", following):
        return False
    return bool(re.search(r"\{[A-Za-z_]\w*\}\s*/[^\s|}`]+|https?://[^\s|`]+|/(?:api|wallet|game)[^\s|}`]*", following, re.I)
                and re.search(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE)\s*:", following, re.I))
