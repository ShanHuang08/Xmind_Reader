from __future__ import annotations

import unittest

from generator.reference_selector import selected_categories
from generator.draft_validator import _validate_output_section
from generator.test_case_generator import (
    _behavior_module,
    _user_behavior_case_category,
    _user_behavior_output_section,
    _user_behavior_selectors,
)
from xmind_writer.metersphere_xmind_writer import _build_sheet


class UserBehaviorRoutingTests(unittest.TestCase):
    def test_debit_credit_aliases_allow_nested_categories(self) -> None:
        errors = []
        _validate_output_section(
            {
                "output_section": "User Behavior > Debit and Credit > Jackpot / FreeSpin",
                "category": "freespin",
            },
            "$.test_cases[0]",
            errors,
        )
        _validate_output_section(
            {
                "output_section": "User Behavior > Cancel Debit > Adjustment",
                "category": "cancel_settlement_adjustment",
            },
            "$.test_cases[1]",
            errors,
        )
        self.assertEqual(errors, [])

    def test_capability_support_selects_freespin_and_jackpot(self) -> None:
        categories = selected_categories(
            {"supports": {"free_spin": True, "jackpot": True}},
            {"parameter_semantics": {}},
        )
        self.assertIn("freespin", categories)
        self.assertIn("jackpot", categories)

    def test_freespin_and_jackpot_share_fixed_branch(self) -> None:
        reference = {"module": "bet and settle", "path": "FreeSpin"}
        for category in ("freespin", "jackpot"):
            output = _user_behavior_output_section(category, reference)
            self.assertEqual(
                output,
                "User Behavior > Bet and Settle > Jackpot / FreeSpin",
            )
            self.assertEqual(_behavior_module(output, reference), "Jackpot / FreeSpin")

    def test_adjustment_routes_by_source_module(self) -> None:
        bet_reference = {
            "module": "bet and settle",
            "path": "modify_settlement_adjustment",
        }
        cancel_reference = {
            "module": "cancel Bet",
            "path": "modify_settlement_adjustment",
        }
        self.assertEqual(
            _user_behavior_output_section(
                "modify_settlement_adjustment", bet_reference
            ),
            "User Behavior > Bet and Settle > Adjustment",
        )
        self.assertEqual(
            _user_behavior_output_section(
                "cancel_settlement_adjustment", cancel_reference
            ),
            "User Behavior > Cancel Bet > Adjustment",
        )
        self.assertEqual(
            _user_behavior_case_category(
                "modify_settlement_adjustment", cancel_reference
            ),
            "cancel_settlement_adjustment",
        )
        self.assertIn(
            ("cancel_bet", "modify_settlement_adjustment"),
            _user_behavior_selectors("modify_settlement_adjustment", set()),
        )

    def test_special_account_titles_override_behavior_category(self) -> None:
        phrases = (
            "timeout player",
            "timeout user",
            "error player",
            "error user",
            "result0 player",
            "result0 user",
            "refund0 player",
            "refund0 user",
            "cancel player",
            "cancel user",
            "delay10s player",
            "delay10s user",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                reference = {
                    "module": "bet and settle",
                    "path": "modify_settlement_adjustment",
                    "scenario": f"Check {phrase} behavior",
                }
                output = _user_behavior_output_section(
                    "modify_settlement_adjustment", reference
                )
                self.assertEqual(
                    output,
                    "User Behavior > Bet and Settle > Special accounts",
                )
                self.assertEqual(_behavior_module(output, reference), "Special accounts")

    def test_title_subcategories_do_not_route_under_balance(self) -> None:
        reference = {
            "module": "balance",
            "path": "Get Player balance",
            "scenario": "Get player balance with timeout user",
        }
        output = _user_behavior_output_section("balance", reference)
        self.assertEqual(output, "User Behavior > Get Player balance")
        errors = []
        _validate_output_section(
            {"output_section": output, "category": "balance"},
            "$.test_cases[0]",
            errors,
        )
        self.assertEqual(errors, [])

    def test_player_game_status_titles_override_behavior_category(self) -> None:
        for phrase in (
            "game status is abnormal",
            "player status is abnormal",
            "game status is abnornal",
            "player status is abnornal",
        ):
            with self.subTest(phrase=phrase):
                reference = {
                    "module": "bet and settle",
                    "path": "modify_settlement_adjustment",
                    "scenario": f"Check ReBetResult when {phrase}",
                }
                output = _user_behavior_output_section(
                    "modify_settlement_adjustment", reference
                )
                self.assertEqual(
                    output,
                    "User Behavior > Bet and Settle > Player / Game status",
                )
                self.assertEqual(
                    _behavior_module(output, reference), "Player / Game status"
                )

    def test_writer_precreates_fixed_empty_categories(self) -> None:
        sheet = _build_sheet({"vendor": "vendor", "test_cases": []})
        root = sheet["rootTopic"]
        titles = self._paths(root)
        self.assertIn(
            "功能用例 > Regression > Vendor_integration > vendor > User Behavior > Bet and Settle > Jackpot / FreeSpin",
            titles,
        )
        self.assertIn(
            "功能用例 > Regression > Vendor_integration > vendor > User Behavior > Bet and Settle > Adjustment",
            titles,
        )
        self.assertIn(
            "功能用例 > Regression > Vendor_integration > vendor > User Behavior > Cancel Bet > Adjustment",
            titles,
        )

    def _paths(self, topic: dict, parent: str = "") -> set[str]:
        title = str(topic.get("title", ""))
        path = f"{parent} > {title}" if parent else title
        output = {path}
        children = topic.get("children", {}).get("attached", [])
        for child in children:
            if isinstance(child, dict):
                output.update(self._paths(child, path))
        return output


if __name__ == "__main__":
    unittest.main()
