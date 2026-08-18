from __future__ import annotations

import unittest

from generator.test_case_generator import (
    DEFAULT_MAX_DECIMAL_PLACES,
    _amount_decimal_case,
    _amount_decimal_cases,
    _infer_amount_decimal_places,
)


class AmountDecimalBoundaryTests(unittest.TestCase):
    def test_explicit_confluence_decimal_range_generates_max_and_max_plus_one(self) -> None:
        endpoint = {"request_parameters": []}
        parameter = {
            "name": "amount",
            "type": "BigDecimal",
            "description": "Maximum 3 decimal places",
        }
        valid, invalid = _amount_decimal_cases(endpoint, parameter)
        self.assertEqual(valid, ("amount Input 3 decimal numbers", '"amount": 100.123'))
        self.assertEqual(invalid, ("amount Input 4 decimal numbers", '"amount": 100.1234'))

    def test_missing_definition_defaults_to_eight_and_nine(self) -> None:
        endpoint = {"request_example": {"amount": 1.25}, "request_parameters": []}
        parameter = {"name": "amount", "type": "decimal"}
        self.assertEqual(_infer_amount_decimal_places(endpoint, parameter), DEFAULT_MAX_DECIMAL_PLACES)
        valid, invalid = _amount_decimal_cases(endpoint, parameter)
        self.assertEqual(valid[0], "amount Input 8 decimal numbers")
        self.assertIn("100.12345678", valid[1])
        self.assertEqual(invalid[0], "amount Input 9 decimal numbers")
        self.assertIn("100.123456789", invalid[1])
        self.assertEqual(_amount_decimal_case(endpoint, parameter), invalid)

    def test_numeric_string_preserves_json_string_format(self) -> None:
        endpoint = {"request_parameters": []}
        parameter = {"name": "amount", "type": "numeric string", "remark": "scale: 2"}
        valid, invalid = _amount_decimal_cases(endpoint, parameter)
        self.assertEqual(valid[1], '"amount": "100.12"')
        self.assertEqual(invalid[1], '"amount": "100.123"')


if __name__ == "__main__":
    unittest.main()
