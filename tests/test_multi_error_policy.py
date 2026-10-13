from __future__ import annotations

import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from generator.multi_error_policy import candidate_codes, resolve, resolve_behavior
from generator.test_case_generator import (
    _insufficient_funds_error,
    _negative_amount_error,
    _step_error,
)


class MultiErrorPolicyTests(unittest.TestCase):
    def test_unmatched_multiple_errors_are_left_to_existing_fallback(self) -> None:
        errors = [
            {"code": "ERROR_A", "context": "first"},
            {"code": "ERROR_B", "context": "second"},
        ]

        self.assertIsNone(
            resolve(vendor="Example", candidate_errors=errors, mutation_kind="wrong_type")
        )
        self.assertEqual(candidate_codes(errors), {"ERROR_A", "ERROR_B"})

    def test_single_error_does_not_enter_multi_error_policy(self) -> None:
        self.assertIsNone(
            resolve(
                vendor="Example",
                candidate_errors=[{"code": "ERROR_A"}],
                mutation_kind="wrong_type",
            )
        )

    def test_hub88_selects_syntax_for_missing_and_blank(self) -> None:
        errors = [
            {
                "code": "RS_ERROR_WRONG_SYNTAX",
                "context": "syntax",
            },
            {
                "code": "RS_ERROR_WRONG_TYPES",
                "context": "types",
            },
        ]

        for mutation_kind in ("missing", "blank"):
            selected = resolve(
                vendor="Hub88",
                candidate_errors=errors,
                mutation_kind=mutation_kind,
            )
            self.assertEqual(selected["code"], "RS_ERROR_WRONG_SYNTAX")
            self.assertEqual(selected["source"], "documented")

    def test_hub88_selects_types_for_wrong_type(self) -> None:
        errors = [
            {"code": "RS_ERROR_WRONG_SYNTAX", "context": "syntax"},
            {"code": "RS_ERROR_WRONG_TYPES", "context": "types"},
        ]

        selected = resolve(
            vendor="Hub88",
            candidate_errors=errors,
            mutation_kind="wrong_type",
        )

        self.assertEqual(selected["code"], "RS_ERROR_WRONG_TYPES")
        self.assertIn(selected["code"], candidate_codes(errors))

    def test_hub88_token_space_selects_invalid_token_not_expired(self) -> None:
        errors = [
            {"code": "RS_ERROR_INVALID_TOKEN", "context": "Unknown token"},
            {"code": "RS_ERROR_TOKEN_EXPIRED", "context": "Expired token"},
        ]

        selected = resolve(
            vendor="Hub88",
            candidate_errors=errors,
            mutation_kind="space",
            parameter={"name": "token", "type": "string"},
        )

        self.assertEqual(selected["code"], "RS_ERROR_INVALID_TOKEN")

    def test_hub88_token_expiry_is_behavior_only(self) -> None:
        errors = [
            {"code": "RS_ERROR_INVALID_TOKEN", "context": "Unknown token"},
            {"code": "RS_ERROR_TOKEN_EXPIRED", "context": "Expired token"},
        ]

        self.assertEqual(
            resolve_behavior(
                vendor="Hub88",
                error_codes=errors,
                category="balance",
                scenario="Terminate the token then get player balance",
            )["code"],
            "RS_ERROR_TOKEN_EXPIRED",
        )
        self.assertIsNone(
            resolve_behavior(
                vendor="Hub88",
                error_codes=errors,
                category="rollback",
                scenario="Terminate the game then do cancel Bet",
            )
        )

    def test_documented_parameter_specific_error_overrides_generic_policy(self) -> None:
        context = {
            "vendor": "Hub88",
            "parameter_error": {
                "code": "RS_ERROR_WRONG_SYNTAX",
                "source": "documented",
            },
            "parameter_error_candidates": [
                {"code": "RS_ERROR_INVALID_GAME", "context": "Unknown game_code"},
                {"code": "RS_ERROR_WRONG_SYNTAX", "context": "syntax"},
                {"code": "RS_ERROR_WRONG_TYPES", "context": "types"},
            ],
        }
        selected = _step_error(
            context,
            {},
            {"name": "gameCode", "type": "string"},
            {
                "code": "RS_ERROR_INVALID_GAME",
                "source": "documented",
                "description": "Unknown game_code",
            },
            "space",
        )
        self.assertEqual(selected["code"], "RS_ERROR_INVALID_GAME")

    def test_insufficient_funds_error_matches_vendor_document_wording(self) -> None:
        selected = _insufficient_funds_error(
            {
                "error_codes": [
                    {
                        "code": "RS_ERROR_NOT_ENOUGH_MONEY",
                        "context": "The user’s balance is insufficient to place a bet.",
                    }
                ]
            }
        )
        self.assertEqual(selected["code"], "RS_ERROR_NOT_ENOUGH_MONEY")
        self.assertEqual(selected["source"], "documented")

    def test_negative_amount_error_requires_negative_amount_wording(self) -> None:
        selected = _negative_amount_error(
            {
                "error_codes": [
                    {
                        "code": "AMOUNT_NOT_NEGATIVE",
                        "context": "The amount cannot be negative.",
                    }
                ]
            }
        )
        self.assertEqual(selected["code"], "AMOUNT_NOT_NEGATIVE")


if __name__ == "__main__":
    unittest.main()
