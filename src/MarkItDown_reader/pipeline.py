"""Convert, normalize, serialize, and read vendor docs into one flat directory."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import uuid
from MarkItDown_reader.contracts import SCHEMA, digest, document_status, identifier, payload_hash, require, validate_document
from MarkItDown_reader.markdown_renderer import render_canonical_markdown
from MarkItDown_reader.registry import normalize
from MarkItDown_reader.review_package import package, import_extraction, decision_template, apply_decisions
from MarkItDown_reader.source_chunker import chunk_source
from MarkItDown_reader.reader import declares_canonical, parse_canonical, read_canonical_markdown
from MarkItDown_reader.exporter import export_files
from .artifact_store import ArtifactStore, read_json, read_json_from_text, json_file
from .source_loader import acquire, convert, converter_signature, display_url


def conversion_meta(path: Path):
    source_id, entry = ArtifactStore._lookup(path)
    if not entry or path.name != entry.get("files", {}).get("converted.md"):
        return None
    meta = entry.get("source", {})
    require(meta.get("converted_sha256") == digest(path.read_bytes()), "Converted file hash mismatch")
    return meta


def normalization_manifest(path: Path):
    manifest_path = path.parent / "manifest.json"
    if not path.name.endswith("full_text.md") or not manifest_path.exists():
        return None
    source_id, entry = ArtifactStore._lookup(path)
    if not entry or path.name != entry.get("files", {}).get("full_text.md"):
        return None
    result = deepcopy(entry)
    result["source_id"] = source_id
    result["source"] = entry.get("source", {})
    result["normalization"].update({"files": entry["files"], "hashes": entry.get("hashes", {})})
    return result["normalization"]


def verify_normalization(path: Path, manifest):
    doc = read_canonical_markdown(path, manifest.get("markdown_sha256") if manifest else None)
    require(bool(doc["normalization_id"]), "Missing normalization ID")
    identifier(doc["normalization_id"]); identifier(doc["conversion_id"])
    if not manifest:
        return doc, "unavailable", None
    meta = manifest.get("source")
    require(isinstance(meta, dict), "Missing source metadata")
    for key, field in (("source_id", "source_id"), ("vendor", "vendor"), ("origin", "source_origin"), ("conversion_id", "conversion_id")):
        require(meta.get(key) == doc[field], "Canonical source identity mismatch")
    converted_name = manifest["files"]["converted.md"]
    converted = path.parent / converted_name
    require(converted.exists() and digest(converted.read_bytes()) == doc["converted_sha256"], "Original conversion hash mismatch")
    validate_document(doc, converted.read_text(encoding="utf-8"))
    return doc, manifest.get("evidence_status", "verified"), meta


def conversion_files(meta, source, notes):
    blocks = chunk_source(source)
    lines = source.splitlines()
    sections = [{**block, "content_markdown": "\n".join(lines[block["line_start"]-1:block["line_end"]])} for block in blocks]
    result = {"converted.md": source, "sections.json": json_file({"version": 1, "blocks": sections})}
    if meta["origin"] == "openapi":
        from MarkItDown_reader.registry import OPENAPI_PREFIX
        result["source_payload.json"] = source[len(OPENAPI_PREFIX):]
    return result


def persist_conversion(store, acquired, args):
    source_id = args.source_id or "source_" + acquired["locator_hash"][:20]
    identifier(source_id)
    meta = {"vendor": store.vendor, "source_id": source_id, "origin": acquired["kind"],
            "locator_hash": acquired["locator_hash"], "source_name": acquired["source_name"],
            "source_url": display_url(args.url or args.source_url) if (args.url or args.source_url) else "",
            "input_sha256": digest(acquired["bytes"]), "acquired_sha256": acquired["acquired_sha256"],
            "acquisition": acquired["acquisition"], "converter": converter_signature(acquired["kind"], args.converter)}
    entry = store.register_source(meta)
    current = entry.get("source", {})
    converted_path = store.file(source_id, "converted.md")
    key = digest(meta)
    if not args.force and current.get("conversion_key") == key and converted_path.exists() and digest(converted_path.read_bytes()) == current.get("converted_sha256"):
        return current, converted_path.read_text(encoding="utf-8"), converted_path, current.get("conversion_warnings", [])
    source, notes = convert(acquired, args.converter, args.input)
    meta["converted_sha256"] = digest(source)
    meta["conversion_id"] = "conversion_" + digest([key, meta["converted_sha256"]])
    meta["conversion_key"] = key
    meta["conversion_warnings"] = notes
    store.write_files(source_id, conversion_files(meta, source, notes), {"source": meta, "conversion_status": "degraded" if notes else "success"})
    return meta, source, converted_path, notes


def import_conversion(store, meta, source, old_path):
    require(meta["converted_sha256"] == digest(source), "Conversion hash mismatch")
    entry = store.register_source(meta)
    path = store.file(meta["source_id"], "converted.md")
    if not path.exists() or digest(path.read_bytes()) != meta["converted_sha256"]:
        store.write_files(meta["source_id"], conversion_files(meta, source, meta.get("conversion_warnings", [])), {"source": meta})
    return path


def publish_normalization(store, meta, doc, conversion_path, audit, key):
    candidates = deepcopy(doc["operations"])
    candidate_errors = deepcopy(doc["error_codes"])
    selected_ids = {op["operation_id"] for op in candidates
                    if op.get("in_scope") and op.get("selection_status") == "selected"}
    selected = deepcopy(doc)
    selected["operations"] = [op for op in candidates if op["operation_id"] in selected_ids]
    selected["error_codes"] = [row for row in candidate_errors
                                if row.get("scope") == "document" or row.get("scope") in selected_ids]
    selection = selected.get("extensions", {}).get("endpoint_selection", {})
    selection["candidate_operation_count"] = len(candidates)
    selection["selected_operation_count"] = len(selected["operations"])
    selected["extensions"]["endpoint_selection"] = selection
    selected["status"] = document_status(selected)
    selected["normalization_id"] = "normalization_" + digest([key, payload_hash(selected)])
    validate_document(selected, selected["source_markdown"])
    markdown = render_canonical_markdown(selected)
    require(parse_canonical(markdown) == selected, "Canonical round-trip failed")
    lines = markdown.splitlines()
    starts = {op["operation_id"]: lines.index(f"### Operation: {op['operation_id']}") + 1 for op in selected["operations"]}
    provenance = {"converted_sha256": meta["converted_sha256"], "markdown_sha256": digest(markdown),
        "operations": {op["operation_id"]: {"canonical_line_start": starts[op["operation_id"]], "evidence": op["evidence"]} for op in selected["operations"]}}
    blocks = [{**b, "source_id": meta["source_id"], "normalization_id": selected["normalization_id"],
        "line_basis": "converted.md", "source_sha256": selected["converted_sha256"],
        "content_markdown": "\n".join(selected["source_markdown"].splitlines()[b["line_start"]-1:b["line_end"]])} for b in selected["coverage"]]
    normalization = {"normalization_id": selected["normalization_id"], "source": meta, "status": selected["status"],
        "cache_key": key, "markdown_sha256": digest(markdown), "provenance": provenance,
        "conversion_warnings": meta.get("conversion_warnings", [])}
    selected_errors = selected["error_codes"]
    files = {"full_text.md": markdown, "sections.json": json_file({"version": 1, "blocks": blocks}),
        "operation_index.json": json_file(selected["operations"]), "endpoint_index.json": json_file([
            {"operation_id": op["operation_id"], "api_name": op["operation_name"], "method": op["http_method"],
             "endpoint": op["url_or_path"], "discriminator": op["discriminator"], "role": op["role"],
             "selection_status": op.get("selection_status"), "selection_reason": op.get("selection_reason"),
             "usage_logic": op.get("usage_logic"), "review_status": op["review_status"], "section_ids": op["section_ids"]}
            for op in selected["operations"] if op["review_status"] != "rejected"]),
        "error_codes.json": json_file(selected_errors), "api_summary.md": render_api_summary(doc),
        "raw_doc.json": json_file({"schema_version": 1, "vendor": doc["vendor"], "source_id": doc["source_id"],
            "source_origin": doc["source_origin"], "conversion_id": doc["conversion_id"],
            "source_sha256": doc["converted_sha256"], "title": Path(meta.get("source_name", "")).stem,
            "source_markdown_ref": store.entry(meta["source_id"])["files"]["converted.md"],
            "sections": [{"section_id": op["source_section"].get("number", op["operation_id"]),
                "title": op["source_section"].get("title", op["operation_name"]),
                "line_start": op["source_section"].get("line_start"),
                "line_end": op["source_section"].get("line_end"),
                "operation_id": op["operation_id"], "content": op.get("logic", "")}
                for op in selected["operations"]],
            "unmapped_sections": selected["coverage"], "endpoints": selected["operations"],
            "error_codes": selected_errors, "endpoint_selection": doc["extensions"].get("endpoint_selection", {}),
            "strategy": doc["strategy"]}),
        "report.json": json_file({"normalization_status": selected["status"],
            "coverage": selected["coverage"], "endpoint_selection": selection,
            "strategy": doc["strategy"], "evidence_status": "verified"}),
        **audit}
    store.write_files(meta["source_id"], files, {"normalization": normalization})
    return store.file(meta["source_id"], "full_text.md")


def render_api_summary(doc):
    lines = [f"# {doc['vendor']} API Summary", "", f"Source: `{doc['source_id']}` ({doc['source_origin']})", "",
             f"Discovered API candidates: {len(doc['operations'])}",
             f"Selected for game-wallet flow: {sum(bool(op.get('in_scope')) for op in doc['operations'])}", "",
             "## Scope and flow", "", "Target roles: " + ", ".join(f"`{r}`" for r in doc.get("extensions", {}).get("endpoint_selection", {}).get("scope_roles", [])), "",
             "```text", json.dumps(doc.get("extensions", {}).get("endpoint_selection", {}).get("flow", []), ensure_ascii=False, indent=2), "```", "",
             "## Discovered APIs", ""]
    for op in doc["operations"]:
        lines.extend([f"## {op['operation_name']}", "",
            f"- Method: `{op['http_method'] or 'unknown'}`", f"- Endpoint: `{op['url_or_path'] or 'unknown'}`",
            f"- Role: `{op.get('role') or 'unclassified'}` ({op.get('role_confidence', 'none')} confidence)",
            f"- Selection: `{op.get('selection_status', 'unclassified')}` — {op.get('selection_reason', '')}",
            f"- Review: `{op['review_status']}`"])
        if op.get("usage_logic"):
            lines.extend([f"- Expected wallet-flow usage: {op['usage_logic']}"])
        if op.get("role_basis"):
            lines.extend(["- Classification evidence: " + "; ".join(op["role_basis"])])
        section = _summary_logic(op.get("logic", ""))
        if section:
            lines.extend(["", "### Source logic", "", section])
        params = op.get("parameters", [])
        if params:
            lines.extend(["", "### Parameters", "", "| Direction | Name | Type | Required | Description |", "|---|---|---|---|---|"])
            for item in params:
                try:
                    value = json.loads(item["raw"])
                except (KeyError, TypeError, json.JSONDecodeError):
                    value = {"name": item.get("name", ""), "direction": item.get("direction", "")}
                clean = lambda v: str(v or "").replace("|", "\\|").replace("\n", " ")
                required = value.get("required")
                if required is None:
                    required = False
                if isinstance(required, bool):
                    required = "Y" if required else "N"
                lines.append("| " + " | ".join(clean(v) for v in
                    (value.get("direction"), value.get("name"), value.get("type"), required,
                     value.get("description"))) + " |")
        if op.get("status_codes"):
            lines.extend(["", "### Status codes", "", ", ".join(f"`{c}`" for c in op["status_codes"])])
        if op.get("examples"):
            lines.extend(["", f"Examples retained: {len(op['examples'])} (see `raw_doc.json` and `full_text.md`)"])
        lines.extend(["", f"Source lines: {op.get('source_section', {}).get('line_start', '?')}–{op.get('source_section', {}).get('line_end', '?')}", ""])
    if not doc["operations"]:
        lines.extend(["No endpoints were confidently extracted.", "", "See `converted.md` and `raw_doc.json` for retained source content."])
    return "\n".join(lines).rstrip() + "\n"


def _summary_logic(value):
    """Keep explanatory source prose in the summary; raw_doc retains every line."""
    kept = []
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or "|" in stripped or re.match(r"^\s*[{}\[\]`]", stripped):
            continue
        if re.match(r"^(?:API Specification|Copyright|Request Body|Response Body|Headers?|Request:|Response:|Possible Status Codes?:|Status codes\b|Example:|Response Example:|OK Response|Error Response)\b", stripped, re.I):
            continue
        if re.match(r"^[\"']?[A-Za-z_][\w.-]*[\"']?\s*:\s*", stripped):
            continue
        if re.match(r"^(?:\d+\s+)?(?:requestId|timestamp|sessionId|playerId|statusCode|currency|balance)\b", stripped, re.I):
            continue
        kept.append(stripped)
    # Retain source order while removing adjacent duplicate fragments.
    compact = []
    for line in kept:
        if not compact or compact[-1] != line:
            compact.append(line)
    return "\n".join(compact[:24])


def parse_and_publish(store, path):
    manifest = normalization_manifest(path)
    doc, evidence_status, meta = verify_normalization(path, manifest)
    require(doc["vendor"] == store.vendor, "Vendor mismatch")
    if doc["source_id"] not in store.manifest()["sources"]:
        meta = {"vendor": doc["vendor"], "source_id": doc["source_id"], "origin": doc["source_origin"],
            "locator_hash": "standalone-" + doc["converted_sha256"], "source_name": path.name,
            "converted_sha256": doc["converted_sha256"], "conversion_id": doc["conversion_id"],
            "conversion_warnings": []}
        store.register_source(meta)
        blocks = chunk_source(doc["source_markdown"])
        lines = doc["source_markdown"].splitlines()
        sections = [{**b, "content_markdown": "\n".join(lines[b["line_start"]-1:b["line_end"]])} for b in blocks]
        store.write_files(doc["source_id"], {"converted.md": doc["source_markdown"],
            "full_text.md": path.read_text(encoding="utf-8"),
            "sections.json": json_file({"version": 1, "blocks": sections})},
            {"source": meta, "normalization": {"normalization_id": doc["normalization_id"],
                "source": meta, "status": doc["status"], "markdown_sha256": digest(path.read_bytes()),
                "evidence_status": "unavailable"}})
    files = export_files(doc, evidence_status)
    # Canonical parser exports references as IDs; all section content lives in sections.json.
    sections = read_json(store.file(doc["source_id"], "sections.json"))
    section_ids = {b["block_id"] for b in sections["blocks"]}
    operation_rows = read_json_from_text(files.get("operation_index.json", "[]"))
    raw_doc_path = store.file(doc["source_id"], "raw_doc.json")
    if raw_doc_path.exists():
        raw_candidates = read_json(raw_doc_path).get("endpoints", [])
        if isinstance(raw_candidates, list):
            operation_rows = deepcopy(raw_candidates)
    for op in operation_rows:
        op["section_ids"] = [sid for sid in op.get("section_ids", []) if sid in section_ids]
    files["operation_index.json"] = json_file(operation_rows)
    warnings = (manifest or {}).get("conversion_warnings", [])
    complete = doc["status"] == "complete" and evidence_status == "verified" and not warnings
    report = {"parse_status": "success", "normalization_status": doc["status"], "evidence_status": evidence_status,
        "conversion_warnings": warnings, "total_operations": len(operation_rows), "total_sections": len(doc["coverage"]),
        "selected_endpoints": sum(bool(op.get("in_scope")) for op in doc["operations"]),
        "selected_endpoint_details": [{"name": op["operation_name"], "method": op.get("http_method"),
            "endpoint": op.get("url_or_path"), "role": op.get("role")}
            for op in doc["operations"] if op.get("in_scope") and op.get("review_status") != "rejected"],
        "error_code_count": len(read_json_from_text(files.get("error_codes.json", "[]"))),
        "endpoint_selection": doc.get("extensions", {}).get("endpoint_selection", {}),
        "source_id": doc["source_id"], "normalization_id": doc["normalization_id"],
        "quality_status": "complete" if complete else "partial"}
    files["report.json"] = json_file(report)
    store.write_files(doc["source_id"], files, {"parse": {"parse_id": "parse_" + digest([digest(path.read_bytes()), files]),
        "markdown_sha256": digest(path.read_bytes()), "status": report["quality_status"]}})
    return (0 if complete else 3), {**report, "full_text": str(path),
        "files": {k: str(store.file(doc["source_id"], k)) for k in
                  (*files.keys(), "api_summary.md", "raw_doc.json") if k in store.entry(doc["source_id"])["files"]},
        "parse_directory": str(store.root)}


def execute(args):
    local = Path(args.input).resolve() if args.input else None
    text = local.read_bytes().decode("utf-8") if local and local.suffix.lower() in {".md", ".markdown"} else None
    canonical = bool(text and declares_canonical(text))
    parent = None; meta = None; doc = None
    if canonical:
        doc = parse_canonical(text)
        if args.parent_normalization:
            require(args.stage == "normalize", "Canonical edits require normalize stage")
            bundle = read_json(Path(args.parent_normalization).resolve())
            source_id = doc["source_id"]
            entry = bundle.get("sources", {}).get(source_id)
            require(isinstance(entry, dict), "Parent manifest has no matching source")
            parent_info = deepcopy(entry["normalization"])
            parent_info.update({"files": entry["files"], "hashes": entry.get("hashes", {})})
            parent_path = local.parent / entry["files"]["full_text.md"]
            parent, evidence_status, meta = verify_normalization(parent_path, parent_info)
            require(evidence_status == "verified", "Parent normalization must have verified source evidence")
            for key in ("vendor", "source_id", "conversion_id", "source_origin", "converted_sha256", "source_markdown"):
                require(doc[key] == parent[key], f"Edit cannot change {key}")
        else:
            require(args.stage in {"all", "read"}, "Canonical editing requires --parent-normalization")
            manifest = normalization_manifest(local)
            doc, evidence_status, meta = verify_normalization(local, manifest)
        vendor = doc["vendor"]
    elif local:
        require(args.stage != "read", "read requires canonical Markdown")
        meta = conversion_meta(local)
        vendor = meta["vendor"] if meta else args.vendor
    else:
        vendor = args.vendor
    require(bool(vendor), "--vendor is required for new sources")
    identifier(vendor)
    require(not args.vendor or args.vendor == vendor, "Vendor does not match input artifact")
    if meta:
        require(not args.source_id or args.source_id == meta["source_id"], "Source ID mismatch")
        require(not args.source_url, "Managed provenance cannot be overridden")
    store = ArtifactStore(Path(args.output), vendor)
    source_id = meta["source_id"] if meta else (doc["source_id"] if canonical else args.source_id)
    run_id = uuid.uuid4().hex
    try:
        with store.lock():
            if canonical and parent is None:
                result = parse_and_publish(store, local)
            else:
                if meta:
                    source = parent["source_markdown"] if parent else text
                    old_converted = local.parent / bundle["sources"][doc["source_id"]]["files"]["converted.md"] if parent else local
                    conversion_path = import_conversion(store, meta, source, old_converted)
                    notes = meta.get("conversion_warnings", [])
                else:
                    acquired = acquire(args)
                    meta, source, conversion_path, notes = persist_conversion(store, acquired, args)
                source_id = meta["source_id"]
                if not source.strip():
                    result = (3, {"status": "empty_output", "converted": str(conversion_path)})
                elif args.stage == "convert":
                    result = (3 if notes else 0, {"status": "degraded" if notes else "success", "converted": str(conversion_path), "warnings": notes})
                elif parent:
                    doc["normalization_id"] = ""
                    doc["extensions"]["parent_normalization"] = parent["normalization_id"]
                    for op in doc["operations"]: op["review_status"] = "pending"
                    for block in doc["coverage"]: block.update(state="pending", reason="Edited revision requires review")
                    doc["status"] = document_status(doc)
                    validate_document(doc, source)
                    candidate = {"document": doc, "candidate_hash": digest(doc)}
                    template = decision_template(candidate)
                    store.write_files(source_id, {"candidate.json": json_file(candidate), "review_decisions.json": json_file(template)})
                    result = (3, {"status": "pending_review", "candidate": str(store.file(source_id, "candidate.json")),
                        "decisions_template": str(store.file(source_id, "review_decisions.json")), "converted": str(conversion_path)})
                elif args.export_review:
                    base = normalize(source, meta); validate_document(base, source)
                    review = package(base); template = decision_template({"document": base, "candidate_hash": digest(base)})
                    files = {"review_package.json": json_file(review), "candidate.json": json_file({"document": base, "candidate_hash": digest(base)}),
                             "review_decisions.json": json_file(template)}
                    store.write_files(source_id, files)
                    result = (3, {"status": "pending_review", "review_package": str(store.file(source_id, "review_package.json")),
                        "candidate": str(store.file(source_id, "candidate.json")),
                        "extraction_template": str(store.file(source_id, "review_package.json")),
                        "decisions_template": str(store.file(source_id, "review_decisions.json")),
                        "converted": str(conversion_path)})
                else:
                    if args.import_candidate:
                        from MarkItDown_reader.contracts import new_document
                        base = new_document(meta, source, chunk_source(source))
                    else:
                        base = normalize(source, meta)
                    validate_document(base, source); audit = {}
                    candidate = None
                    if args.import_extraction:
                        extracted = read_json(Path(args.import_extraction)); candidate = import_extraction(extracted, base)
                        template = decision_template(candidate)
                        store.write_files(source_id, {"candidate.json": json_file(candidate), "review_decisions.json": json_file(template)})
                        result = (3, {"status": "pending_review", "candidate": str(store.file(source_id, "candidate.json")),
                            "decisions_template": str(store.file(source_id, "review_decisions.json")), "converted": str(conversion_path)})
                        normalized = None
                    elif args.import_candidate:
                        candidate = read_json(Path(args.import_candidate)); decisions = read_json(Path(args.review_decisions))
                        normalized = apply_decisions(candidate, decisions, base)
                        audit.update({"candidate.json": json_file(candidate), "review_decisions.json": json_file(decisions)})
                    else:
                        normalized = base
                    if normalized is not None:
                        key = digest([meta["conversion_id"], normalized, audit, "renderer-1", "chunker-1"])
                        full_text = publish_normalization(store, meta, normalized, conversion_path, audit, key)
                        if args.stage == "normalize":
                            result = (0 if normalized["status"] == "complete" else 3, {"status": normalized["status"], "full_text": str(full_text)})
                        else:
                            result = parse_and_publish(store, full_text)
                        if candidate is not None:
                            result[1].update({"candidate": str(store.file(source_id, "candidate.json")),
                                "decisions_template": str(store.file(source_id, "review_decisions.json")),
                                "converted": str(conversion_path)})
                    if notes and result[0] == 0: result = (3, {**result[1], "conversion_warnings": notes})
            code, report = result
            store.update_report(source_id or "unknown", {"run_id": run_id, "stage": args.stage,
                "status": "complete" if code == 0 else "needs_attention", "exit_code": code,
                "updated_at": datetime.now(timezone.utc).isoformat(), "result": report})
            return code, {**report, "report": str(store.report_path), "manifest": str(store.manifest_path)}
    except Exception as exc:
        store.update_report(source_id or "unknown", {"run_id": run_id, "stage": args.stage,
            "status": "failed", "error_type": type(exc).__name__, "message": str(exc),
            "updated_at": datetime.now(timezone.utc).isoformat()})
        raise
