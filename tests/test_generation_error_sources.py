from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from generator.case_generation_context import _select_parameter_error
from generator.draft_builder import _markdown_error_codes
from generator.test_case_generator import _expected_error_response


class SupplementaryErrorCodeTests(unittest.TestCase):
    def test_extracts_parameter_context_and_response_from_markdown_table(self) -> None:
        markdown = """
| No | Code | Param message required? | Description | Example |
|---|---|---|---|---|
|4|303|Optional|There's some missing param.<br>Bad parameter request|{<br>"status": false,<br>"error_code": 303,<br>"message": "Invalid Token",<br>}|
"""

        errors = _markdown_error_codes(markdown)

        self.assertEqual(errors[0]["code"], "303")
        self.assertIn("Bad parameter request", errors[0]["context"])
        self.assertEqual(
            errors[0]["response_json"],
            {"status": False, "error_code": 303, "message": "Invalid Token"},
        )

    def test_selected_parameter_error_keeps_documented_response(self) -> None:
        response = {"status": False, "error_code": 303, "message": "Invalid Token"}

        selected = _select_parameter_error(
            [
                {
                    "code": "303",
                    "context": "Missing parameter. Bad parameter request",
                    "response_json": response,
                }
            ]
        )

        self.assertEqual(selected["response_json"], response)
        self.assertEqual(_expected_error_response({}, {}, selected), response)


if __name__ == "__main__":
    unittest.main()
