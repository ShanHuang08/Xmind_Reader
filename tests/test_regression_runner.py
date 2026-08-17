from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from regression.vendor_case_baseline import (
    baseline_document,
    build_case_profile,
    compare_case_profile,
    intrinsic_coverage_errors,
)
from run_vendor_regression import (
    _command_output_failure,
    _load_baseline,
    _run_preflight,
    _validate_summary_content,
    discover_vendors,
    validate_vendor_outputs,
)


class VendorDiscoveryTests(unittest.TestCase):
    def test_discovers_root_and_nested_documents_in_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Vendor_Zeta.doc").touch()
            nested = root / "nested"
            nested.mkdir()
            (nested / "vendor_alpha.DOCX").touch()

            self.assertEqual(discover_vendors(root), ["alpha", "Zeta"])

    def test_ignores_non_vendor_and_unsupported_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Vendor_Alea.doc").touch()
            (root / "Vendor_PdfOnly.pdf").touch()
            (root / "Alea.doc").touch()
            (root / ".DS_Store").touch()

            self.assertEqual(discover_vendors(root), ["Alea"])

    def test_rejects_duplicate_vendor_documents_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Vendor_Alea.doc").touch()
            nested = root / "nested"
            nested.mkdir()
            (nested / "vendor_alea.docx").touch()

            with self.assertRaisesRegex(RuntimeError, "Duplicate vendor documents"):
                discover_vendors(root)

    def test_rejects_empty_vendor_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "No Vendor_\\*\\.doc"):
                discover_vendors(Path(directory))

    def test_rejects_missing_vendor_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with self.assertRaisesRegex(RuntimeError, "does not exist"):
                discover_vendors(missing)


class OutputValidationTests(unittest.TestCase):
    def test_stale_validation_report_is_not_marked_xmind_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output" / "Alea"
            output.mkdir(parents=True)
            (output / "draft_test_cases.json").write_text(
                '{"vendor":"Alea","test_cases":[{}]}', encoding="utf-8"
            )
            (output / "Alea_test_cases.xmind").write_bytes(b"not-a-zip")
            (output / "Alea_test_cases_validation_report.json").write_text(
                '{"valid":true,"errors":[],"draft_case_count":1,"parsed_case_count":1}',
                encoding="utf-8",
            )
            (output / "Alea_test_cases_summary.md").write_text("summary", encoding="utf-8")

            result = validate_vendor_outputs(root, "Alea", time.time() + 10)

            self.assertFalse(result["draft_valid"])
            self.assertFalse(result["xmind_valid"])


class CaseCoverageTests(unittest.TestCase):
    def test_missing_endpoint_fails_against_baseline(self) -> None:
        baseline = build_case_profile(
            _draft([_endpoint("/bet", ["amount"]), _endpoint("/win", ["amount"])])
        )
        current = build_case_profile(_draft([_endpoint("/bet", ["amount"])]))

        result = compare_case_profile(current, baseline)

        self.assertFalse(result["passed"])
        self.assertIn("/win", result["missing_endpoint_groups"])

    def test_missing_operation_variant_fails_against_baseline(self) -> None:
        endpoint = _endpoint("/transactions", [])
        endpoint["operation_variants"] = [
            {"operation": "BET", "request_parameters": [_parameter("amount")]},
            {"operation": "WIN", "request_parameters": [_parameter("amount")]},
        ]
        baseline = build_case_profile(
            _draft(
                [endpoint],
                cases=[
                    _parameter_case("/transactions", "amount", "BET"),
                    _parameter_case("/transactions", "amount", "WIN"),
                ],
            )
        )
        current_endpoint = _endpoint("/transactions", [])
        current_endpoint["operation_variants"] = [
            {"operation": "BET", "request_parameters": [_parameter("amount")]}
        ]
        current = build_case_profile(
            _draft(
                [current_endpoint],
                cases=[_parameter_case("/transactions", "amount", "BET")],
            )
        )

        result = compare_case_profile(current, baseline)

        self.assertFalse(result["passed"])
        self.assertIn("/transactions::WIN", result["missing_endpoint_groups"])

    def test_api_parameter_decrease_over_threshold_fails(self) -> None:
        baseline = build_case_profile(
            _draft(
                [_endpoint("/bet", [f"p{i}" for i in range(20)])],
                cases=[_parameter_case("/bet", f"p{i}") for i in range(20)],
            )
        )
        current = build_case_profile(
            _draft(
                [_endpoint("/bet", [f"p{i}" for i in range(18)])],
                cases=[_parameter_case("/bet", f"p{i}") for i in range(18)],
            )
        )

        result = compare_case_profile(current, baseline)

        self.assertTrue(
            any("API parameter test count decreased" in error for error in result["errors"])
        )

    def test_documented_skip_reason_prevents_missing_coverage_failure(self) -> None:
        draft = _draft(
            [_endpoint("/bet", ["amount", "legacyField"])],
            cases=[_parameter_case("/bet", "amount")],
        )
        draft["parameter_coverage_skips"] = [
            {
                "endpoint": "/bet",
                "operation": "",
                "parameter": "legacyField",
                "skip_reason": "Vendor marks this field as unsupported.",
            }
        ]

        profile = build_case_profile(draft)

        self.assertEqual(intrinsic_coverage_errors(profile), [])
        self.assertEqual(
            profile["endpoints"]["/bet"]["skipped_parameters"][0]["parameter"],
            "legacyField",
        )

    def test_baseline_read_does_not_modify_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            content = json.dumps(baseline_document({"Zeta": {"total_cases": 1}}))
            path.write_text(content, encoding="utf-8")

            _load_baseline(path, allow_missing=False)

            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_baseline_document_is_deterministic(self) -> None:
        profiles = {"Zeta": {"total_cases": 2}, "alpha": {"total_cases": 1}}

        first = json.dumps(baseline_document(profiles), sort_keys=False)
        second = json.dumps(baseline_document(dict(reversed(list(profiles.items())))), sort_keys=False)

        self.assertEqual(first, second)
        self.assertEqual(list(baseline_document(profiles)["vendors"]), ["alpha", "Zeta"])

    def test_traceback_is_failure_even_without_nonzero_exit(self) -> None:
        output = "INFO start\nTraceback (most recent call last):\nValueError: broken\n"

        self.assertEqual(_command_output_failure(output), "ValueError: broken")

    def test_preflight_finds_nested_user_behavior_map(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "run_new_vendor.py").touch()
            nested = root / "input_xmind"
            nested.mkdir()
            (nested / "User_Behavior_map.xmind").touch()

            result = _run_preflight(root)

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["user_behavior_map"], "input_xmind/User_Behavior_map.xmind")

    def test_summary_counts_must_match_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            path.write_text(
                "Vendor 這次總共產生 3 筆，其中：\n"
                "| User Behavior | 1 |\n| API parameter test | 2 |\n",
                encoding="utf-8",
            )
            errors: list[str] = []

            _validate_summary_content(
                path,
                {"total_cases": 4, "sections": {"User Behavior": 1, "API parameter test": 3}},
                errors,
            )

            self.assertEqual(len(errors), 2)


def _parameter(name: str) -> dict[str, str]:
    return {"name": name, "type": "string", "required": "Y"}


def _endpoint(path: str, parameters: list[str]) -> dict[str, object]:
    return {
        "endpoint": path,
        "request_parameters": [_parameter(name) for name in parameters],
        "operation_variants": [],
    }


def _parameter_case(endpoint: str, parameter: str, operation: str = "") -> dict[str, str]:
    return {
        "output_section": "API parameter test",
        "category": "parameter_validation",
        "endpoint": endpoint,
        "endpoint_operation": operation,
        "parameter": parameter,
    }


def _draft(
    endpoints: list[dict[str, object]], cases: list[dict[str, str]] | None = None
) -> dict[str, object]:
    generated = cases
    if generated is None:
        generated = [
            _parameter_case(str(endpoint["endpoint"]), str(parameter["name"]))
            for endpoint in endpoints
            for parameter in endpoint.get("request_parameters", [])
        ]
    return {"endpoint_roles": endpoints, "test_cases": generated}


if __name__ == "__main__":
    unittest.main()
