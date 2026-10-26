"""Flat, version-aware artifacts in the vendor_markdown directory."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import os, re, uuid
from MarkItDown_reader.contracts import ContractError, digest, identifier, json_text, require, strict_json

ROOT = Path(__file__).resolve().parents[2]
PROTECTED_NAMES = {"vendor_pdf", "vendor_url", "xmind_detail", "input_xmind", "new_vendor_source", "output"}


def read_json(path: Path):
    return strict_json(path.read_text(encoding="utf-8"))


def atomic_text(path: Path, value: str):
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(value, encoding="utf-8", newline="\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, value):
    atomic_text(path, json_text(value) + "\n")


class ArtifactStore:
    def __init__(self, output: Path, vendor: str):
        identifier(vendor)
        output = output.resolve()
        require(not any(p.lower() in PROTECTED_NAMES for p in output.parts), "Output overlaps a protected legacy directory")
        intended = output / vendor / "vendor_markdown"
        self.root = intended.resolve()
        require(self.root == intended, "Symlink/junction output redirection is not supported")
        self.root.mkdir(parents=True, exist_ok=True)
        self.vendor = vendor
        self.manifest_path = self.root / "manifest.json"
        self.report_path = self.root / "report.json"

    def manifest(self):
        if not self.manifest_path.exists():
            return {"schema_version": 1, "vendor": self.vendor, "sources": {}}
        data = read_json(self.manifest_path)
        require(data.get("vendor") == self.vendor and isinstance(data.get("sources"), dict), "Invalid vendor manifest")
        return data

    @staticmethod
    def _lookup(path: Path):
        manifest_path = path.parent / "manifest.json"
        if not manifest_path.is_file():
            return None, None
        try:
            data = read_json(manifest_path)
        except (OSError, ValueError):
            return None, None
        for source_id, entry in data.get("sources", {}).items():
            if path.name in entry.get("files", {}).values():
                return source_id, entry
        return None, None

    def source_for_path(self, path: Path):
        base = path.name
        for source_id, item in self.manifest()["sources"].items():
            if base in item.get("files", {}).values():
                return source_id, item
        return None, None

    def register_source(self, meta: dict):
        identifier(meta["source_id"])
        manifest = self.manifest()
        sources = manifest["sources"]
        entry = sources.get(meta["source_id"])
        identity = {k: meta[k] for k in ("vendor", "source_id", "origin", "locator_hash")}
        if entry:
            require(entry.get("identity") == identity, "Source ID belongs to another source")
        else:
            used = {name for current in sources.values() for name in current.get("files", {}).values()}
            if not sources:
                prefix = ""
            else:
                slug = re.sub(r"[^A-Za-z0-9_-]+", "_", meta.get("source_name", "source")).strip("_")[:32] or "source"
                prefix = f"{slug}_{meta['source_id'][:8]}."
            logical = ("converted.md", "full_text.md", "operation_index.json", "endpoint_index.json", "error_codes.json",
                       "sections.json", "source_payload.json", "review_package.json", "candidate.json", "review_decisions.json",
                       "api_summary.md", "raw_doc.json")
            files = {key: prefix + key for key in logical}
            require(not set(files.values()).intersection(used), "Source filename collision")
            entry = {"identity": identity, "files": files, "hashes": {}}
            sources[meta["source_id"]] = entry
        # Add newly introduced logical artifacts to existing manifests without
        # changing the names or contents of any prior files.
        entry.setdefault("files", {})
        entry.setdefault("hashes", {})
        used = {name for sid, current in sources.items() if sid != meta["source_id"]
                for name in current.get("files", {}).values()}
        existing_names = set(entry["files"].values())
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", meta.get("source_name", "source")).strip("_")[:32] or "source"
        prefix = "" if len(sources) == 1 and not existing_names else f"{slug}_{meta['source_id'][:8]}."
        for logical in ("api_summary.md", "raw_doc.json"):
            if logical not in entry["files"]:
                candidate = prefix + logical
                require(candidate not in used and candidate not in existing_names, "Source filename collision")
                entry["files"][logical] = candidate
                existing_names.add(candidate)
        entry.setdefault("source", {}).update(meta)
        atomic_json(self.manifest_path, manifest)
        return entry

    def entry(self, source_id: str):
        require(source_id in self.manifest()["sources"], "Unknown source ID")
        return self.manifest()["sources"][source_id]

    def file(self, source_id: str, logical: str) -> Path:
        entry = self.entry(source_id)
        require(logical in entry["files"], "Unknown artifact name")
        return self.root / entry["files"][logical]

    def write_files(self, source_id: str, files: dict[str, str], update: dict | None = None):
        manifest = self.manifest()
        entry = manifest["sources"].get(source_id)
        require(entry is not None, "Unknown source ID")
        for logical, content in files.items():
            if logical == "report.json":
                report = read_json_from_text(content)
                self.update_report(source_id, report)
                continue
            require(logical in entry["files"], f"Unknown artifact name: {logical}")
            path = self.root / entry["files"][logical]
            atomic_text(path, content)
            entry["hashes"][logical] = digest(path.read_bytes())
        if update:
            for key, value in update.items():
                if key == "source":
                    previous_hash = entry.get("source", {}).get("converted_sha256")
                    if value.get("converted_sha256") and previous_hash and value["converted_sha256"] != previous_hash:
                        for stage in ("normalization", "parse"):
                            if entry.get(stage):
                                entry[stage]["status"] = "stale"
                    entry.setdefault("source", {}).update(value)
                else:
                    if key == "normalization" and entry.get("normalization") and value.get("markdown_sha256") != entry["normalization"].get("markdown_sha256") and entry.get("parse"):
                        entry["parse"]["status"] = "stale"
                    entry[key] = value
        atomic_json(self.manifest_path, manifest)

    def update_report(self, source_id: str, result: dict):
        report = read_json(self.report_path) if self.report_path.exists() else {"vendor": self.vendor, "sources": {}}
        report["sources"][source_id] = result
        atomic_json(self.report_path, report)

    @contextmanager
    def lock(self):
        lock = self.root / ".writer.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ContractError("Another writer is active; inspect .writer.lock before removing a stale lock") from exc
        try:
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)


def json_file(value):
    return json_text(value) + "\n"


def read_json_from_text(value):
    return strict_json(value)
