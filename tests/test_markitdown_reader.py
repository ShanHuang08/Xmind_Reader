from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import io
import json
import sys
import tempfile
import unittest
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from MarkItDown_reader_main import main
from MarkItDown_reader.artifact_store import ArtifactStore, read_json
from MarkItDown_reader.contracts import ContractError, digest, json_text, validate_document
from MarkItDown_reader.registry import normalize, register, STRATEGIES
from MarkItDown_reader.markdown_renderer import render_canonical_markdown
from MarkItDown_reader.reader import parse_canonical


class CanonicalDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "api.md"
        self.source.write_text('# Balance\nMethod: POST\nPath:\n/wallet/balance\n\nExample:\n```json\n{"id": 1}\n```\n', encoding="utf-8")
        self.out = self.root / "details"

    def cli(self, *args, vendor=True):
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = main(["--output", str(self.out), *(["--vendor", "Demo"] if vendor else []), *map(str, args)])
        return code, json.loads(stdout.getvalue()) if stdout.getvalue().strip() else {}

    def read_source(self, *args):
        return self.cli("--input", self.source, *args)

    def test_markdown_end_to_end_is_partial_and_keeps_all_source(self):
        code, result = self.read_source()
        self.assertEqual(code, 3)
        doc = parse_canonical(Path(result["full_text"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["source_markdown"], self.source.read_text(encoding="utf-8"))
        self.assertEqual(doc["operations"][0]["url_or_path"], "/wallet/balance")
        index = read_json(Path(result["parse_directory"]) / "endpoint_index.json")
        self.assertEqual(index[0]["method"], "POST")
        self.assertEqual(result["evidence_status"], "verified")

    def test_review_import_decision_and_offline_read(self):
        _, export = self.read_source("--stage", "normalize", "--export-review")
        template = Path(export["extraction_template"])
        _, imported = self.read_source("--stage", "normalize", "--import-extraction", template)
        candidate_path = Path(imported["candidate"])
        decisions = read_json(Path(imported["decisions_template"]))
        for values in decisions["operations"].values():
            for key in values:
                values[key] = "accept"
        for block in decisions["coverage"].values():
            block.update(state="retained_unmapped", reason="Reviewed source; all API operations accounted for")
        decisions_path = self.root / "decisions.json"
        decisions_path.write_text(json_text(decisions), encoding="utf-8")
        with patch("MarkItDown_reader.pipeline.normalize", side_effect=AssertionError("Review must not rerun strategy")):
            code, reviewed = self.cli("--input", imported["converted"], "--stage", "normalize",
                                      "--import-candidate", candidate_path, "--review-decisions", decisions_path)
        self.assertEqual(code, 0)
        decisions["candidate_hash"] = "0" * 64
        decisions_path.write_text(json_text(decisions), encoding="utf-8")
        self.assertEqual(self.cli("--input", imported["converted"], "--stage", "normalize",
            "--import-candidate", candidate_path, "--review-decisions", decisions_path)[0], 1)
        self.source.unlink()
        with patch("MarkItDown_reader.source_loader.convert", side_effect=AssertionError("must not convert")), \
             patch("MarkItDown_reader.source_loader.acquire", side_effect=AssertionError("must not acquire")):
            code, result = self.cli("--input", reviewed["full_text"], "--stage", "read", vendor=False)
        self.assertEqual(code, 0)
        self.assertEqual(result["evidence_status"], "verified")

    def test_stale_candidate_and_fabricated_evidence_rejected(self):
        _, export = self.read_source("--stage", "normalize", "--export-review")
        template = Path(export["extraction_template"])
        data = read_json(template)
        data["document"]["operations"][0]["url_or_path"] = "/invented"
        template.write_text(json_text(data), encoding="utf-8")
        code, _ = self.read_source("--stage", "normalize", "--import-extraction", template)
        self.assertEqual(code, 1)
        data["converted_sha256"] = "0" * 64
        template.write_text(json_text(data), encoding="utf-8")
        self.assertEqual(self.read_source("--stage", "normalize", "--import-extraction", template)[0], 1)

    def test_zero_endpoints_still_produces_sections(self):
        self.source.write_text("# Overview\nA descriptive document.\n", encoding="utf-8")
        code, result = self.read_source()
        self.assertEqual(code, 3)
        self.assertEqual(result["total_operations"], 0)
        self.assertTrue(read_json(Path(result["parse_directory"]) / "sections.json")["blocks"])

    def test_canonical_tampering_and_unknown_version_never_fall_back(self):
        _, result = self.read_source()
        path = Path(result["full_text"])
        path.write_text(path.read_text(encoding="utf-8") + "Extra text\n", encoding="utf-8")
        with patch("MarkItDown_reader.pipeline.normalize", side_effect=AssertionError("no fallback")):
            self.assertEqual(self.cli("--input", path)[0], 1)
        self.source.write_text("<!-- vendor-markdown:vendor-markdown/v9 -->\n", encoding="utf-8")
        self.assertEqual(self.read_source()[0], 1)

    def test_source_conversion_tampering_blocks_read(self):
        _, result = self.read_source()
        canonical = Path(result["full_text"])
        converted = next(canonical.parent.glob("*converted.md"))
        converted.write_text("Changed source", encoding="utf-8")
        self.assertEqual(self.cli("--input", canonical, "--stage", "read")[0], 1)

    def test_standalone_file_read_does_not_claim_verified(self):
        _, result = self.read_source()
        standalone = self.root / "standalone.md"
        standalone.write_bytes(Path(result["full_text"]).read_bytes())
        code, report = self.cli("--input", standalone, "--stage", "read")
        self.assertEqual(code, 3)
        self.assertEqual(report["evidence_status"], "unavailable")

    def test_unrelated_data_and_generation_inputs_unchanged(self):
        protected = [self.out / "Demo" / "endpoints.json", self.out / "Demo" / "error_codes.json",
                     self.out / "Demo" / "vendor_pdf" / "full_text.md",
                     self.out / "Demo" / "vendor_url" / "endpoint_index.json"]
        for p in protected:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("legacy-data", encoding="utf-8")
        hashes = {p: digest(p.read_bytes()) for p in protected}
        self.read_source()
        self.read_source("--force")
        self.assertEqual(hashes, {p: digest(p.read_bytes()) for p in protected})

    def test_conversion_cache_and_force_respect_stage(self):
        pdf = self.root / "test.pdf"
        pdf.write_bytes(b"synthetic fixture")
        with patch("MarkItDown_reader.pipeline.convert", return_value=(self.source.read_text(encoding="utf-8"), [])) as convert:
            self.assertEqual(self.cli("--input", pdf, "--stage", "convert")[0], 0)
            self.cli("--input", pdf, "--stage", "convert")
            self.assertEqual(convert.call_count, 1)
            self.cli("--input", pdf, "--stage", "convert", "--force")
            self.assertEqual(convert.call_count, 2)
        self.assertFalse(list((self.out / "Demo" / "vendor_markdown").glob("*full_text.md")))

    def test_normalization_failure_keeps_converted_md(self):
        with patch("MarkItDown_reader.pipeline.normalize", side_effect=ValueError("injected failure")):
            self.assertEqual(self.read_source()[0], 1)
        self.assertTrue(list((self.out / "Demo" / "vendor_markdown").glob("*converted.md")))
        report = read_json(self.out / "Demo" / "vendor_markdown" / "report.json")
        self.assertTrue(any(x["status"] == "failed" for x in report["sources"].values()))

    def test_openapi_full_payload_retained(self):
        path = self.root / "openapi.json"
        payload = {"openapi": "3.0.0", "paths": {"/wallet": {"post": {"summary": "Wallet", "requestBody": {"$ref": "#/components/body"}}}},
                   "components": {"body": {"description": "Preserved definition"}}}
        path.write_text(json_text(payload), encoding="utf-8")
        code, report = self.cli("--input", path)
        self.assertEqual(code, 3)
        self.assertEqual(read_json(next(self.out.rglob("source_payload.json"))), payload)
        self.assertIn("Preserved definition", Path(report["full_text"]).read_text(encoding="utf-8"))

    def test_strategy_extension_and_round_trip(self):
        meta = {"source_id": "demo", "vendor": "Demo", "origin": "markdown", "conversion_id": "conversion_test"}
        source = self.source.read_text(encoding="utf-8")
        base = normalize(source, meta)
        name = "test_passthrough"
        register(name, lambda text, metadata, blocks: deepcopy(base))
        self.addCleanup(lambda: STRATEGIES.pop(name))
        result = normalize(source, meta, name)
        self.assertEqual(parse_canonical(render_canonical_markdown(result)), base)

    def test_invalid_cli_combinations_are_usage_errors(self):
        for args in [("--input", self.source, "--timeout", "30"),
                     ("--url", "https://example.test", "--stage", "read"),
                     ("--input", self.source, "--stage", "convert"),
                     ("--input", self.source, "--import-extraction", "a.json"),
                     ("--input", self.source, "--review-decisions", "a.json")]:
            with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                self.cli(*args)
            self.assertEqual(raised.exception.code, 2)

    def test_output_cannot_target_legacy_directories(self):
        for directory in ("vendor_pdf", "vendor_url", "output", "xmind_detail"):
            with self.assertRaises(ContractError):
                ArtifactStore(self.root / directory, "Demo")

    def test_writer_lock_and_id_collision(self):
        store = ArtifactStore(self.out, "Demo")
        with store.lock():
            with self.assertRaises(ContractError), store.lock():
                pass
        self.read_source("--source-id", "fixed")
        second = self.root / "other.md"
        second.write_text("another source", encoding="utf-8")
        self.assertEqual(self.cli("--input", second, "--source-id", "fixed")[0], 1)

    def test_missing_method_remains_partial_after_review(self):
        from MarkItDown_reader.contracts import document_status
        source = "# Balance\nPath: /balance\n"
        doc = normalize(source, {"vendor": "Demo", "source_id": "test", "origin": "markdown", "conversion_id": "test"})
        for block in doc["coverage"]:
            block.update(state="mapped", reason="Reviewed")
        doc["operations"][0]["review_status"] = "accepted"
        doc["status"] = document_status(doc)
        validate_document(doc)
        self.assertEqual(doc["status"], "partial")
        del doc["operations"][0]["http_method"]
        with self.assertRaises(ContractError):
            validate_document(doc)

    def test_parent_edit_creates_pending_revision_and_keeps_parent(self):
        _, original = self.read_source()
        parent = Path(original["full_text"])
        before = parent.read_bytes()
        doc = parse_canonical(before.decode("utf-8"))
        doc["operations"][0]["operation_name"] = "Reviewed Balance"
        edited = self.root / "edited.md"
        edited.write_text(render_canonical_markdown(doc), encoding="utf-8", newline="\n")
        code, result = self.cli("--input", edited, "--stage", "normalize", "--parent-normalization", parent.parent / "manifest.json")
        self.assertEqual(code, 3)
        updated = parse_canonical(Path(result["full_text"]).read_text(encoding="utf-8"))
        self.assertEqual(updated["extensions"]["parent_normalization"], doc["normalization_id"])
        self.assertEqual(updated["operations"][0]["review_status"], "pending")
        self.assertEqual(before, parent.read_bytes())

    def test_parse_failure_keeps_canonical_and_source(self):
        with patch("MarkItDown_reader.pipeline.export_files", side_effect=ValueError("parse failed")):
            self.assertEqual(self.read_source()[0], 1)
        canonical = next(self.out.rglob("full_text.md"))
        self.assertTrue(list(self.out.rglob("converted.md")))
        self.assertEqual(self.cli("--input", canonical, "--stage", "read")[0], 3)

    def test_url_acquisition_and_content_type_are_explicit(self):
        from types import SimpleNamespace
        response = SimpleNamespace(content_type="text/markdown", text="# Balance\nPOST /balance\n",
            final_url="https://example.test/docs?token=secret", fetch_method="urllib", sha256="a" * 64)
        with patch("url_reader.url_fetcher.fetch_url", return_value=response) as fetch:
            code, result = self.cli("--url", "https://example.test/docs?token=secret", "--timeout", "5")
            self.assertEqual(code, 3)
            fetch.assert_called_once_with("https://example.test/docs?token=secret", "", "", 5)
        manifest = read_json(self.out / "Demo" / "vendor_markdown" / "manifest.json")
        meta = manifest["sources"][next(iter(manifest["sources"]))]["source"]
        self.assertNotIn("secret", json_text(meta))
        response.content_type = "application/pdf"
        with patch("url_reader.url_fetcher.fetch_url", return_value=response):
            self.assertEqual(self.cli("--url", "https://example.test/docs")[0], 1)

    def test_malformed_external_result_fails_cleanly(self):
        _, exported = self.read_source("--stage", "normalize", "--export-review")
        path = Path(exported["extraction_template"])
        value = read_json(path)
        value["document"]["operations"] = [42]
        path.write_text(json_text(value), encoding="utf-8")
        self.assertEqual(self.read_source("--stage", "normalize", "--import-extraction", path)[0], 1)

    def test_multiple_sources_and_same_url_actions_do_not_overwrite(self):
        self.source.write_text("# Bet\nPOST /wallet\naction: bet\n# Win\nPOST /wallet\naction: win\n", encoding="utf-8")
        _, first = self.read_source()
        doc = parse_canonical(Path(first["full_text"]).read_text(encoding="utf-8"))
        self.assertEqual(len(doc["operations"]), 2)
        second = self.root / "second.md"
        second.write_text("# Second\nGET /balance\n", encoding="utf-8")
        _, result = self.cli("--input", second)
        self.assertNotEqual(result["source_id"], first["source_id"])
        self.assertTrue(Path(first["full_text"]).exists())

    def test_generator_and_xmind_semantics_unchanged_by_new_artifacts(self):
        from generator.draft_builder import build_draft
        from generator.test_case_generator import generate_test_cases_file
        from xmind_writer.metersphere_xmind_writer import write_xmind_from_draft
        from xmind_writer.xmind_validator import validate_generated_xmind
        import zipfile
        vendor = self.out / "Demo"
        vendor.mkdir(parents=True)
        fixtures = {"capability_profile.json": {}, "error_codes.json": [
            {"code": "303", "context": "Missing parameter. Bad parameter request", "response_json": {"error_code": 303}}], "endpoints.json": [
            {"endpoint": "/balance", "method": "POST", "request_parameters": [
                {"name": "token", "type": "string", "required": True, "description": "Player token"}]}]}
        for name, value in fixtures.items():
            (vendor / name).write_text(json_text(value), encoding="utf-8")
        hashes = {name: digest((vendor / name).read_bytes()) for name in fixtures}
        def snapshot():
            path = build_draft("Demo", self.out, self.root / "generated")
            generate_test_cases_file(path, self.root / "empty-knowledge")
            draft = read_json(path)
            self.assertTrue(draft["test_cases"])
            xmind = write_xmind_from_draft(draft, self.root / "cases.xmind")
            self.assertTrue(validate_generated_xmind(xmind, draft)["valid"])
            with zipfile.ZipFile(xmind) as archive:
                content = json.loads(archive.read("content.json"))
            def semantic(value):
                if isinstance(value, dict):
                    return {k: semantic(v) for k, v in value.items() if k != "id"}
                if isinstance(value, list):
                    return [semantic(v) for v in value]
                return value
            return draft["test_cases"], semantic(content)
        before = snapshot()
        self.assertEqual(self.read_source()[0], 3)
        self.assertEqual(before, snapshot())
        self.assertEqual(hashes, {name: digest((vendor / name).read_bytes()) for name in fixtures})

    @unittest.skipUnless(importlib.util.find_spec("markitdown"), "Install requirements-reader.txt for conversion smoke tests")
    def test_real_markitdown_html_and_text_pdf_smoke(self):
        html = self.root / "test.html"
        html.write_text("<html><body><h1>Balance</h1><p>POST /balance</p><table><tr><th>Name</th></tr><tr><td>token</td></tr></table></body></html>", encoding="utf-8")
        code, result = self.cli("--input", html)
        self.assertEqual(code, 3)
        self.assertIn("token", Path(result["full_text"]).read_text(encoding="utf-8"))
        # Minimal single-page text PDF; no real vendor files used for calibration.
        stream = b"BT /F1 12 Tf 50 750 Td (POST /balance) Tj ET"
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
        raw = b"%PDF-1.4\n"
        offsets = []
        for i, obj in enumerate(objects, 1):
            offsets.append(len(raw))
            raw += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
        start = len(raw)
        raw += b"xref\n0 6\n0000000000 65535 f \n"
        raw += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
        raw += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
        pdf = self.root / "test.pdf"
        pdf.write_bytes(raw)
        code, result = self.cli("--input", pdf)
        self.assertEqual(code, 3)
        doc = parse_canonical(Path(result["full_text"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["operations"][0]["url_or_path"], "/balance")


if __name__ == "__main__":
    unittest.main()
