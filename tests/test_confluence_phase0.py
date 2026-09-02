from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.run_rovo_phase0 import build_parser, main as phase0_main

from doc_reader.confluence_phase0 import (
    EVIDENCE_SCHEMA_VERSION,
    FixtureSpec,
    Phase0CapabilityError,
    Phase0ConfigurationError,
    Phase0ResponseError,
    REQUIRED_ADMIN_CHECKS,
    ROVO_CONTRACT_VERSION,
    ROVO_MCP_ENDPOINT,
    auth_config_from_env,
    build_content_arguments,
    build_pending_evidence,
    canonical_content_url,
    classify_exception,
    choose_authoritative_markdown,
    ensure_no_running_event_loop,
    extract_page_version,
    extract_content_id,
    extract_resources,
    load_attestation,
    load_manifest,
    manifest_preflight,
    markdown_candidates_from_result,
    markdown_inventory,
    parse_numeric_page_id,
    root_cause_exception,
    select_cloud_id,
    storage_inventory,
    truncation_evidence,
    validate_inventory,
    validate_required_tools,
    validate_response_content_id,
    validate_same_page_version,
    write_evidence,
    _read_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "confluence"


class ConfluencePhase0Tests(unittest.TestCase):
    def test_direct_read_cli_does_not_require_hard_gate_files(self) -> None:
        args = build_parser().parse_args(
            [
                "--read-url",
                "https://company.atlassian.net/wiki/spaces/GA/pages/12345/Page",
                "--auth-mode",
                "personal",
            ]
        )
        self.assertIsNone(args.manifest)
        self.assertIsNone(args.evidence)

    def test_direct_read_cli_rejects_hard_gate_arguments(self) -> None:
        with self.assertRaises(SystemExit):
            phase0_main(
                [
                    "--read-url",
                    "https://company.atlassian.net/wiki/spaces/GA/pages/12345/Page",
                    "--manifest",
                    "phase0/fixture_manifest.example.json",
                ]
            )

    def test_example_manifest_covers_hard_gate_matrix(self) -> None:
        manifest = load_manifest(ROOT / "phase0" / "fixture_manifest.example.json")
        result = manifest_preflight(manifest)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["fixture_count"], 9)

    def test_v1_manifest_schema_is_rejected(self) -> None:
        payload = json.loads((ROOT / "phase0" / "fixture_manifest.example.json").read_text(encoding="utf-8"))
        payload["schema_version"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(Phase0ConfigurationError):
                load_manifest(path)

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
        self.assertEqual(config.endpoint, ROVO_MCP_ENDPOINT)

    def test_auth_config_rejects_v1_and_diagnostic_endpoints(self) -> None:
        base = {
            "ROVO_MCP_ALLOWED_SITES": "company.atlassian.net",
            "ROVO_MCP_EMAIL": "reader@example.invalid",
            "ROVO_MCP_API_TOKEN": "test-secret",
        }
        for endpoint in (
            "https://mcp.atlassian.com/v1/mcp/authv2",
            "https://mcp.atlassian.com/v1/sse",
            "https://mcp.atlassian.com/v2/mcp?tools=all",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(Phase0ConfigurationError):
                auth_config_from_env("personal", {**base, "ROVO_MCP_URL": endpoint})

    def test_canonical_content_url_removes_query_fragment_and_trailing_slash(self) -> None:
        url = "https://company.atlassian.net/wiki/spaces/GA/pages/12345/Page_Name/?x=1#section"
        self.assertEqual(
            canonical_content_url(url),
            "https://company.atlassian.net/wiki/spaces/GA/pages/12345/Page_Name",
        )
        with self.assertRaises(Phase0ConfigurationError):
            canonical_content_url("https://company.atlassian.net/wiki/pages/viewpage.action?pageId=12345")

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
        self.assertEqual(extract_content_id(result), "123456789")
        validate_response_content_id(result, "123456789")

    def test_v2_json_text_envelope_exposes_markdown_identity_and_version(self) -> None:
        result = json.loads((FIXTURES / "rovo_v2_text_page.json").read_text(encoding="utf-8"))
        candidates, envelope = markdown_candidates_from_result(result)
        self.assertIn("# Text envelope", choose_authoritative_markdown(candidates).text)
        self.assertEqual(extract_content_id(result), "123456789")
        self.assertEqual(extract_page_version(result), 7)
        self.assertFalse(truncation_evidence(result)["truncated"])
        self.assertFalse(envelope["structured_content_present"])

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

    def test_v2_content_arguments_are_typed_and_canonical(self) -> None:
        tool = json.loads(
            (FIXTURES / "rovo_v2_get_confluence_content_tool.json").read_text(encoding="utf-8")
        )
        schema = tool["inputSchema"]
        url = "https://company.atlassian.net/wiki/spaces/GA/pages/123/Synthetic#fragment"
        self.assertEqual(
            build_content_arguments(schema, "cloud", url),
            {
                "cloudId": "cloud",
                "content_url": "https://company.atlassian.net/wiki/spaces/GA/pages/123/Synthetic",
                "detail": "full",
                "content_format": "markdown",
                "include_metadata": True,
            },
        )
        with self.assertRaises(Exception):
            build_content_arguments(schema, "cloud", url, "next-token")
        with self.assertRaises(Phase0CapabilityError):
            build_content_arguments(
                {"properties": {"cloudId": {}, "pageId": {}}}, "cloud", url
            )

    def test_v1_page_schema_is_rejected(self) -> None:
        schema = {"properties": {"cloudId": {}, "pageId": {}}}
        with self.assertRaises(Phase0CapabilityError):
            build_content_arguments(
                schema,
                "cloud",
                "https://company.atlassian.net/wiki/spaces/GA/pages/123/Synthetic",
            )

    def test_missing_required_tool_fails_closed(self) -> None:
        with self.assertRaises(Phase0CapabilityError):
            validate_required_tools(["getConfluencePage"])
        validate_required_tools(["getConfluenceContent", "getAccessibleAtlassianResources", "optionalTool"])

    def test_v2_missing_scope_claim_is_authorization(self) -> None:
        error = Phase0ResponseError("session token is missing the scope claim required to authorize")
        self.assertEqual(classify_exception(error), "authorization")

    def test_exception_group_unwraps_phase0_error(self) -> None:
        class FakeExceptionGroup(Exception):
            def __init__(self, *children: BaseException) -> None:
                super().__init__("sdk wrapper")
                self.exceptions = children

        leaf = Phase0ResponseError("actionable")
        group = FakeExceptionGroup(RuntimeError("noise"), leaf)
        self.assertIs(root_cause_exception(group), leaf)

    def test_pending_evidence_declares_v2_contract(self) -> None:
        manifest = load_manifest(ROOT / "phase0" / "fixture_manifest.example.json")
        evidence = build_pending_evidence(manifest, ("personal",), ("offline",))
        self.assertEqual(evidence["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(evidence["rovo_contract_version"], ROVO_CONTRACT_VERSION)
        self.assertEqual(evidence["rovo_endpoint_path"], "/v2/mcp")

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
        "properties": {
            "cloudId": {},
            "content_url": {},
            "detail": {"enum": ["summary", "full"]},
            "content_format": {"enum": ["html", "markdown"]},
            "include_metadata": {"type": "boolean"},
            "cursor": {},
        },
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
            "structuredContent": {
                "content": {
                    "id": "123456789",
                    "body": {"value": markdown, "format": "markdown"},
                    "meta": meta,
                    "version": {"number": 7},
                }
            },
            "content": [],
            "isError": False,
        }

    async def test_continuation_pages_are_joined_in_order(self) -> None:
        class FakeClient:
            def __init__(self, responses: list[dict]) -> None:
                self.responses = iter(responses)
                self.calls: list[tuple[str, dict]] = []

            async def call_tool(self, name: str, arguments: dict) -> dict:
                self.calls.append((name, arguments))
                return next(self.responses)

        client = FakeClient(
            [self.result("# Part one\nbody", has_more=True, cursor="next-1"), self.result("Part two\nend", has_more=False)]
        )
        markdown, envelope, _ = await _read_fixture(client, self.fixture, "cloud", self.schema, 3, 10_000)
        self.assertEqual(markdown, "# Part one\nbody\nPart two\nend")
        self.assertEqual(envelope["page_count"], 2)
        self.assertEqual([name for name, _ in client.calls], ["getConfluenceContent", "getConfluenceContent"])
        self.assertEqual(client.calls[0][1]["detail"], "full")
        self.assertEqual(client.calls[0][1]["content_format"], "markdown")
        self.assertTrue(client.calls[0][1]["include_metadata"])

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
    ROVO_CONTRACT_VERSION,
    ROVO_MCP_ENDPOINT,
