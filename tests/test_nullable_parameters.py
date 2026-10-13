from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from doc_reader.doc_extractor import _annotate_nullable_parameters
from generator.test_case_generator import _blank_step, _is_nullable_parameter


class NullableParameterTests(unittest.TestCase):
    def test_description_marks_parameter_nullable(self) -> None:
        endpoint = {
            "request_parameters": [
                {"name": "round_closed", "type": "boolean", "description": "Can be null."}
            ],
            "request_example": {"round_closed": False},
        }

        _annotate_nullable_parameters(endpoint)

        parameter = endpoint["request_parameters"][0]
        self.assertTrue(parameter["nullable"])
        self.assertEqual(parameter["nullable_source"], "documented_description")
        self.assertEqual(_blank_step(parameter), ("round_closed input null", '"round_closed": null'))

    def test_null_request_example_marks_parameter_nullable(self) -> None:
        endpoint = {
            "request_parameters": [
                {"name": "bet", "type": "string", "description": "Metadata."}
            ],
            "request_example": {"bet": None},
        }

        _annotate_nullable_parameters(endpoint)

        parameter = endpoint["request_parameters"][0]
        self.assertTrue(_is_nullable_parameter(parameter))
        self.assertEqual(parameter["nullable_source"], "request_example")

    def test_non_nullable_parameter_keeps_leave_blank(self) -> None:
        parameter = {"name": "currency", "type": "string", "description": "ISO code."}
        self.assertFalse(_is_nullable_parameter(parameter))
        self.assertEqual(_blank_step(parameter), ("currency leave blank", '"currency": ""'))


if __name__ == "__main__":
    unittest.main()
