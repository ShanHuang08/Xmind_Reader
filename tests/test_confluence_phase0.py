from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from doc_reader.confluence_phase0 import (
    FixtureSpec,
    Phase0CapabilityError,
    Phase0ConfigurationError,
    Phase0ResponseError,
    REQUIRED_ADMIN_CHECKS,
    auth_config_from_env,
    build_page_arguments,
    choose_authoritative_markdown,
    ensure_no_running_event_loop,
    extract_page_version,
    extract_resources,
    load_attestation,
    load_manifest,
    manifest_preflight,
    markdown_candidates_from_result,
    markdown_inventory,
    parse_numeric_page_id,
    select_cloud_id,
    storage_inventory,
    truncation_evidence,
    validate_inventory,
    validate_required_tools,
    validate_same_page_version,
    write_evidence,
    _read_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "confluence"


class ConfluencePhase0Tests(unittest.TestCase):
    def test_example_manifest_covers_hard_gate_matrix(self) -> None:
        manifest = load_manifest(ROOT / "phase0" / "fixture_manifest.example.json")
        result = manifest_preflight(manifest)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["fixture_count"], 9)

    def test_page_id_parser_accepts_canonical_and_viewpage(self) -> None:
        canonical = "https://company.atlassian.net/wiki/spaces/GA/pages/12345/Page"
        viewpage = "https://company.atlassian.net/wiki/pages/viewpage.action?pageId=12345"
        self.assertEqual(parse_numeric_page_id(canonical), "12345")
        self.assertEqual(parse_numeric_page_id(viewpage), "12345")

    def test_page_id_parser_rejects_short_url_in_manifest(self) -> None:
        with self.assertRaises(Phase0ConfigurationError):
            parse_numeric_page_id("https://company.atlassian.net/wiki/x/AbCd")

    def test_auth_config_builds_basic_without_exposing_secret(self) -> None:
        config = auth_config_from_env(
            "personal",
            {
                "ROVO_MCP_ALLOWED_SITES": "company.atlassian.net",
                "ROVO_MCP_EMAIL": "reader@example.invalid",
                "ROVO_MCP_API_TOKEN": "test-secret",
            },
        )
        self.assertTrue(config.authorization.startswith("Basic "))
        self.assertNotIn("test-secret", config.authorization)

    def test_structured_markdown_is_selected_and_inventoried(self) -> None:
        result = json.loads((FIXTURES / "rovo_structured_page.json").read_text(encoding="utf-8"))
        candidates, envelope = markdown_candidates_from_result(result)
        selected = choose_authoritative_markdown(candidates)
        fixture = FixtureSpec(
            "synthetic",
            "basic_content",
            "https://company.atlassian.net/wiki/spaces/GA/pages/123456789/Synthetic",
            markers=("PHASE0_BEGIN", "PHASE0_END"),
            expected_min={"heading_count": 1, "table_count": 1, "code_fence_line_count": 2},
        )
        inventory = markdown_inventory(selected.text, fixture)
        self.assertFalse(validate_inventory(inventory, fixture))
        self.assertTrue(envelope["structured_content_present"])
        self.assertEqual(extract_page_version(result), 7)

    def test_conflicting_markdown_candidates_fail_closed(self) -> None:
        result = {
            "structuredContent": {"markdown": "# One\ncontent"},
            "content": [{"type": "text", "text": "# Two\ncontent"}],
        }
        candidates, _ = markdown_candidates_from_result(result)
        with self.assertRaises(Phase0ResponseError):
            choose_authoritative_markdown(candidates)

    def test_empty_or_malformed_payload_fails_closed(self) -> None:
        candidates, _ = markdown_candidates_from_result({"structuredContent": {"body": ""}, "content": []})
        with self.assertRaises(Phase0ResponseError):
            choose_authoritative_markdown(candidates)

    def test_truncation_signals_and_cursor_are_redacted(self) -> None:
        result = {"structuredContent": {"hasMore": True, "cursor": "opaque-cursor"}}
        evidence = truncation_evidence(result)
        self.assertTrue(evidence["truncated"])
        self.assertNotIn("opaque-cursor", json.dumps({k: v for k, v in evidence.items() if k != "cursor_values"}))
        self.assertEqual(evidence["cursor_values"], ["opaque-cursor"])

    def test_accessible_resource_requires_unique_host_match(self) -> None:
        result = json.loads((FIXTURES / "rovo_resources.json").read_text(encoding="utf-8"))
        resources = extract_resources(result)
        self.assertEqual(select_cloud_id(resources, "company.atlassian.net"), "cloud-secret-shaped-id")
        with self.assertRaises(Phase0CapabilityError):
            select_cloud_id(resources, "missing.atlassian.net")

    def test_page_arguments_reject_unknown_schema(self) -> None:
        schema = {"type": "object", "properties": {"cloudId": {}, "pageId": {}, "cursor": {}}}
        self.assertEqual(
            build_page_arguments(schema, "cloud", "123", "next-token"),
            {"cloudId": "cloud", "pageId": "123", "cursor": "next-token"},
        )
        with self.assertRaises(Phase0CapabilityError):
            build_page_arguments({"properties": {"id": {}}}, "cloud", "123")

    def test_missing_required_tool_fails_closed(self) -> None:
        with self.assertRaises(Phase0CapabilityError):
            validate_required_tools(["getConfluencePage"])
        validate_required_tools(["getConfluencePage", "getAccessibleAtlassianResources", "optionalTool"])

    def test_rest_comparison_requires_same_known_version(self) -> None:
        self.assertEqual(validate_same_page_version(7, 7), [])
        self.assertTrue(validate_same_page_version(None, 7))
        self.assertTrue(validate_same_page_version(7, 8))

    def test_storage_inventory_preserves_complex_structure_counts(self) -> None:
        payload = json.loads((FIXTURES / "rest_storage_page.json").read_text(encoding="utf-8"))
        html = payload["body"]["storage"]["value"]
        fixture = FixtureSpec(
            "storage",
            "merged_nested_table",
            "https://company.atlassian.net/wiki/spaces/GA/pages/123456789/Synthetic",
            markers=("PHASE0_BEGIN", "PHASE0_END"),
        )
        inventory = storage_inventory(html, fixture)
        self.assertEqual(inventory["table_count"], 2)
        self.assertEqual(inventory["nested_table_count"], 1)
        self.assertEqual(inventory["merged_cell_count"], 1)
        self.assertGreaterEqual(inventory["macro_count"], 1)

    def test_attestation_stays_pending_until_every_check_passes(self) -> None:
        pending = load_attestation(ROOT / "phase0" / "admin_attestation.example.json", REQUIRED_ADMIN_CHECKS, "admin")
        self.assertEqual(pending["status"], "pending")
        self.assertEqual(set(pending["missing"]), set(REQUIRED_ADMIN_CHECKS))

    def test_evidence_writer_rejects_environment_secret(self) -> None:
        old = os.environ.get("ROVO_MCP_API_KEY")
        os.environ["ROVO_MCP_API_KEY"] = "never-write-this"
        try:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(Exception):
                    write_evidence(Path(directory) / "evidence.json", {"value": "never-write-this"})
        finally:
            if old is None:
                os.environ.pop("ROVO_MCP_API_KEY", None)
            else:
                os.environ["ROVO_MCP_API_KEY"] = old


class Phase0PaginationTests(unittest.IsolatedAsyncioTestCase):
    fixture = FixtureSpec(
        "page",
        "basic_content",
        "https://company.atlassian.net/wiki/spaces/GA/pages/123456789/Synthetic",
    )
    schema = {
        "type": "object",
        "properties": {"cloudId": {}, "pageId": {}, "cursor": {}},
    }

    async def test_sync_entrypoint_rejects_running_event_loop(self) -> None:
        with self.assertRaises(Phase0ConfigurationError):
            ensure_no_running_event_loop()

    @staticmethod
    def result(markdown: str, *, has_more: bool, cursor: str = "") -> dict:
        meta = {"hasMore": has_more}
        if cursor:
            meta["cursor"] = cursor
        return {
            "structuredContent": {"body": {"markdown": markdown}, "meta": meta, "version": {"number": 7}},
            "content": [],
            "isError": False,
        }

    async def test_continuation_pages_are_joined_in_order(self) -> None:
        class FakeClient:
            def __init__(self, responses: list[dict]) -> None:
                self.responses = iter(responses)

            async def call_tool(self, name: str, arguments: dict) -> dict:
                return next(self.responses)

        client = FakeClient(
            [self.result("# Part one\nbody", has_more=True, cursor="next-1"), self.result("Part two\nend", has_more=False)]
        )
        markdown, envelope, _ = await _read_fixture(client, self.fixture, "cloud", self.schema, 3, 10_000)
        self.assertEqual(markdown, "# Part one\nbody\nPart two\nend")
        self.assertEqual(envelope["page_count"], 2)

    async def test_cursor_loop_fails_closed(self) -> None:
        class LoopClient:
            async def call_tool(self, name: str, arguments: dict) -> dict:
                return Phase0PaginationTests.result("# Partial\nbody", has_more=True, cursor="same")

        with self.assertRaises(Exception) as captured:
            await _read_fixture(LoopClient(), self.fixture, "cloud", self.schema, 3, 10_000)
        self.assertIn("cursor loop", str(captured.exception).lower())

    async def test_total_byte_limit_fails_closed(self) -> None:
        class LargeClient:
            async def call_tool(self, name: str, arguments: dict) -> dict:
                return Phase0PaginationTests.result("# Large\n" + "x" * 500, has_more=False)

        with self.assertRaises(Exception) as captured:
            await _read_fixture(LargeClient(), self.fixture, "cloud", self.schema, 3, 100)
        self.assertIn("max_total_bytes", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
