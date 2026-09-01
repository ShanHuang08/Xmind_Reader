from __future__ import annotations

import unittest

from generator.test_case_generator import (
    _find_example_value,
    _remarks,
    _request_parameter_name,
    _request_payload,
    _sample_value,
)
from doc_reader.doc_extractor import _request_url_example


class ParameterGenerationTests(unittest.TestCase):
    def test_request_example_lookup_is_case_insensitive(self) -> None:
        example = {
            "hash": "{MD5_hash}",
            "token": "{player_token}",
            "gameSessionId": "{mf_session_id}",
        }
        self.assertEqual(_find_example_value(example, "Hash"), "{MD5_hash}")
        self.assertEqual(_find_example_value(example, "Token"), "{player_token}")
        self.assertEqual(
            _find_example_value(example, "gameSessionID"), "{mf_session_id}"
        )

    def test_missing_parameter_example_does_not_create_sample_data(self) -> None:
        self.assertEqual(_sample_value({"name": "unknownField", "type": "String"}), "")

    def test_api_remarks_preserve_encoded_request_url(self) -> None:
        request_url = "https://example.test/api?bet=50%7Ctransaction-001"
        remarks = _remarks(
            {
                "request_url_example": request_url,
                "request_example": {"token": "{player_token}"},
                "success_response_example": {"result": "OK"},
            },
            {"name": "Token"},
        )
        self.assertNotIn("needs to support URL encoded", remarks)
        self.assertIn("bet=50%7Ctransaction-001", remarks)
        self.assertEqual(
            _request_payload({"request_url_example": request_url}),
            "bet=50%7Ctransaction-001",
        )
        self.assertEqual(
            _request_parameter_name(
                {"request_example": {"hash": "{MD5_hash}"}}, "Hash"
            ),
            "hash",
        )

    def test_request_url_example_keeps_multiline_encoded_query(self) -> None:
        source = (
            "https://example.test/api?hash=h\n"
            "&bet=50%7Ctransaction-001\n"
            "&roundId=round-001"
        )
        self.assertEqual(
            _request_url_example(source),
            "https://example.test/api?hash=h&bet=50%7Ctransaction-001&roundId=round-001",
        )


if __name__ == "__main__":
    unittest.main()
