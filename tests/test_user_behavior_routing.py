from __future__ import annotations

from pathlib import Path
import unittest

from generator.draft_validator import _validate_output_section
from generator.reference_selector import selected_categories
from generator.test_case_generator import (
    _behavior_module,
    _game_type_categories,
    _path_matches,
    _user_behavior_case_category,
    _user_behavior_output_section,
    _user_behavior_selectors,
)
from generator.user_behavior_mapping import (
    MAPPING_CONTRACT_VERSION,
    build_user_behavior_mapping_report,
    map_user_behavior_case,
)
from xmind_writer.metersphere_xmind_writer import _build_sheet


class UserBehaviorRoutingTests(unittest.TestCase):
    def test_confluence_checked_game_types_override_game_code_inference(self) -> None:
        context = {
            "capability_profile": {
                "vendor_master_checklist": [
                    {
                        "name": "Game Type",
                        "enabled": True,
                        "selected_values": ["Slot Game", "Video Bingo"],
                    }
                ]
            },
            "game_codes": [
                {"game_type": "Live", "game_name": "Live table", "game_code": "LIVE_1"}
            ],
        }
        self.assertEqual(
            _game_type_categories(context), ["slot_game", "video_bingo"]
        )

    def test_unchecked_game_types_are_not_selected(self) -> None:
        context = {
            "capability_profile": {
                "vendor_master_checklist": [
                    {
                        "name": "Game Type",
                        "enabled": False,
                        "selected_values": [],
                    }
                ]
            },
            "game_codes": [{"game_type": "Slot", "game_code": "SLOT_1"}],
        }
        self.assertEqual(_game_type_categories(context), [])

    def test_combined_mini_instant_win_checkbox_maps_both_categories(self) -> None:
        context = {
            "capability_profile": {
                "vendor_master_checklist": [
                    {
                        "name": "Game Type",
                        "enabled": True,
                        "selected_values": ["Mini Game\n(Instant Win)"],
                    }
                ]
            },
            "game_codes": [],
        }
        self.assertEqual(
            _game_type_categories(context), ["instant_win", "mini_game"]
        )

    def test_debit_credit_aliases_preserve_canonical_leaf(self) -> None:
        errors = []
        _validate_output_section(
            {"output_section": "User Behavior > Debit and Credit > Settle config", "category": "settlement"},
            "$.test_cases[0]",
            errors,
        )
        _validate_output_section(
            {"output_section": "User Behavior > Cancel Debit > Cancel config", "category": "cancel_settlement_adjustment"},
            "$.test_cases[1]",
            errors,
        )
        self.assertEqual(errors, [])

    def test_legacy_and_parent_only_sections_are_rejected(self) -> None:
        for output in (
            "User Behavior > Bet and Settle",
            "User Behavior > Bet and Settle > Jackpot / FreeSpin",
            "User Behavior > Cancel Bet > Adjustment",
            "User Behavior > Bet and Settle > Vendor specific cases",
            "User Behavior > Game type > Slot game",
        ):
            with self.subTest(output=output):
                errors = []
                _validate_output_section(
                    {"output_section": output, "category": "bet"},
                    "$.test_cases[0]",
                    errors,
                )
                self.assertTrue(errors)

    def test_capability_support_selects_freespin_and_jackpot(self) -> None:
        categories = selected_categories(
            {"supports": {"free_spin": True, "jackpot": True}},
            {"parameter_semantics": {}},
        )
        self.assertIn("freespin", categories)
        self.assertIn("jackpot", categories)

    def test_freespin_and_jackpot_route_to_main_flow(self) -> None:
        references = {
            "freespin": {"module": "bet and settle", "path": "FreeSpin > main flow"},
            "jackpot": {"module": "bet and settle", "path": "settle_by_round > Multiple Settlement > jackpot > main flow"},
        }
        for category, reference in references.items():
            with self.subTest(category=category):
                output = _user_behavior_output_section(category, reference)
                self.assertEqual(output, "User Behavior > Bet and Settle > Game type > Main flow")
                self.assertEqual(_behavior_module(output, reference), "Main flow")

    def test_adjustment_routes_by_source_module_and_leaf(self) -> None:
        bet_reference = {"module": "bet and settle", "path": "modify_settlement_adjustment > adjustment config"}
        cancel_reference = {"module": "cancel Bet", "path": "modify_settlement_adjustment > adjustment config"}
        self.assertEqual(
            _user_behavior_output_section("modify_settlement_adjustment", bet_reference),
            "User Behavior > Bet and Settle > Settle config",
        )
        self.assertEqual(
            _user_behavior_output_section("cancel_settlement_adjustment", cancel_reference),
            "User Behavior > Cancel Bet > Cancel config",
        )
        self.assertEqual(
            _user_behavior_case_category("modify_settlement_adjustment", cancel_reference),
            "cancel_settlement_adjustment",
        )
        self.assertIn(
            ("cancel_bet", "modify_settlement_adjustment"),
            _user_behavior_selectors("modify_settlement_adjustment", set()),
        )

    def test_explicit_source_leaf_precedes_title_fallback(self) -> None:
        reference = {
            "module": "bet and settle",
            "path": "modify_settlement_adjustment > adjustment config",
            "scenario": "Check timeout player behavior",
        }
        self.assertEqual(
            _user_behavior_output_section("modify_settlement_adjustment", reference),
            "User Behavior > Bet and Settle > Settle config",
        )

    def test_title_fallback_applies_only_when_leaf_is_missing(self) -> None:
        reference = {
            "module": "bet and settle",
            "path": "modify_settlement_adjustment",
            "scenario": "Check timeout player behavior",
        }
        decision = map_user_behavior_case("modify_settlement_adjustment", reference)
        self.assertEqual(decision.output_section, "User Behavior > Bet and Settle > Special accounts")
        self.assertEqual(decision.rule_id, "legacy.title_special_accounts")

    def test_title_fallback_does_not_route_balance(self) -> None:
        reference = {
            "module": "get player balance",
            "path": "Mandatory > get player balance",
            "scenario": "Get player balance with timeout user",
        }
        self.assertEqual(_user_behavior_output_section("balance", reference), "User Behavior > Get Player balance")

    def test_bet_and_settle_config_has_dedicated_branch(self) -> None:
        for path in (
            "BetAndSettle > Mandatory > BetAndSettle config",
            "BetAndSettle > Has round-end control parameter > BetAndSettle config",
        ):
            with self.subTest(path=path):
                decision = map_user_behavior_case("bet_and_settle", {"module": "bet and settle", "path": path})
                self.assertEqual(decision.output_section, "User Behavior > Bet and Settle > BetAndSettle config")
                self.assertEqual(decision.rule_id, "bet.bet_and_settle_config")

    def test_game_category_modules_use_new_nested_path(self) -> None:
        cases = {
            "Instant Win": "Instant Win",
            "Live game": "Live game",
            "Mini game": "Mini game",
            "Poker game": "Poker game",
            "Slot game": "Slot game",
            "Table game": "Table game",
            "Video Bingo": "Video Bingo",
        }
        for module, leaf in cases.items():
            with self.subTest(module=module):
                decision = map_user_behavior_case("inventory", {"module": module, "path": f"Game category > {leaf}"})
                self.assertEqual(
                    decision.output_section,
                    "User Behavior > Bet and Settle > Game type > Game category > " + leaf,
                )

    def test_path_matching_is_segment_aware_and_excludes_special_tests(self) -> None:
        self.assertTrue(
            _path_matches(
                "settle_by_round > Multiple Settlement > No round-end control parameter > settle config",
                "Multiple Settlement > No round-end control parameter",
            )
        )
        self.assertFalse(_path_matches("Bet config extra", "Bet config"))
        self.assertFalse(_path_matches("Special test cases > Authenticate", "Authenticate"))

    def test_inventory_accounts_for_all_reference_cases(self) -> None:
        root = Path(__file__).resolve().parents[1] / "xmind_detail"
        report = build_user_behavior_mapping_report(root)
        self.assertEqual(report["contract_version"], MAPPING_CONTRACT_VERSION)
        self.assertEqual(report["total_cases"], 203)
        self.assertEqual(report["accounted"], 203)
        self.assertEqual(report["mapped"], 189)
        self.assertEqual(report["excluded"], 14)
        self.assertEqual(report["unmapped"], 0)

    def test_writer_omits_empty_bet_and_settle_config(self) -> None:
        sheet = _build_sheet({"vendor": "vendor", "test_cases": []})
        titles = self._paths(sheet["rootTopic"])
        prefix = "功能用例 > Regression > Vendor_integration > vendor > User Behavior"
        expected = {
            f"{prefix} > Bet and Settle > Game type > Main flow",
            f"{prefix} > Bet and Settle > Bet config",
            f"{prefix} > Bet and Settle > Settle config",
            f"{prefix} > Bet and Settle > Special accounts",
            f"{prefix} > Bet and Settle > Player / Game status",
            f"{prefix} > Cancel Bet > Main flow",
            f"{prefix} > Cancel Bet > Cancel config",
            f"{prefix} > Cancel Bet > Special accounts",
            f"{prefix} > Cancel Bet > Player / Game status",
        }
        self.assertTrue(expected.issubset(titles))
        self.assertNotIn(
            f"{prefix} > Bet and Settle > BetAndSettle config", titles
        )
        self.assertFalse(any("Jackpot / FreeSpin" in path for path in titles))
        self.assertFalse(any("Vendor specific cases" in path for path in titles))
        self.assertFalse(any("Game category" in path for path in titles))

    def test_writer_creates_only_game_categories_with_cases(self) -> None:
        sheet = _build_sheet(
            {
                "vendor": "vendor",
                "test_cases": [
                    {
                        "output_section": (
                            "User Behavior > Bet and Settle > Game type > "
                            "Game category > Slot game"
                        ),
                        "scenario": "slot case",
                    },
                    {
                        "output_section": (
                            "User Behavior > Bet and Settle > Game type > "
                            "Game category > Video Bingo"
                        ),
                        "scenario": "bingo case",
                    },
                ],
            }
        )
        titles = self._paths(sheet["rootTopic"])
        game_category_paths = {
            path.split(" > Game category > ", 1)[1].split(" > ", 1)[0]
            for path in titles
            if " > Game category > " in path
        }
        self.assertEqual(game_category_paths, {"Slot game", "Video Bingo"})

    def test_writer_creates_bet_and_settle_config_when_case_exists(self) -> None:
        sheet = _build_sheet(
            {
                "vendor": "vendor",
                "test_cases": [
                    {
                        "output_section": "User Behavior > Bet and Settle > BetAndSettle config",
                        "scenario": "combined controller config case",
                    }
                ],
            }
        )
        titles = self._paths(sheet["rootTopic"])
        self.assertIn(
            "功能用例 > Regression > Vendor_integration > vendor > User Behavior > "
            "Bet and Settle > BetAndSettle config",
            titles,
        )

    def _paths(self, topic: dict, parent: str = "") -> set[str]:
        title = str(topic.get("title", ""))
        path = f"{parent} > {title}" if parent else title
        output = {path}
        for child in topic.get("children", {}).get("attached", []):
            if isinstance(child, dict):
                output.update(self._paths(child, path))
        return output


if __name__ == "__main__":
    unittest.main()
