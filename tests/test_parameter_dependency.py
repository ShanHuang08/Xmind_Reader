from __future__ import annotations

import unittest

from doc_reader.parameter_dependency import compile_parameter_dependencies
from generator.test_case_generator import (
    _hash_parameter_steps,
    _normal_request_value,
    _parameter_steps,
    _parameter_validation_cases,
    _space_request_line,
)


class ParameterDependencyCompilerTests(unittest.TestCase):
    def test_request_example_values_match_parameter_name_casing(self) -> None:
        endpoint = {
            "request_example": {
                "token": "token-value",
                "hash": "hash-value",
                "gameSessionId": "session-value",
                "payload": {"userID": "user-value"},
            }
        }
        for name, expected in (
            ("Token", '"token-value"'),
            ("Hash", '"hash-value"'),
            ("gameSessionID", '"session-value"'),
            ("userId", '"user-value"'),
        ):
            parameter = {"name": name, "type": "String"}
            self.assertEqual(_normal_request_value(endpoint, parameter), expected)
            self.assertIn(expected.strip('"'), _space_request_line(endpoint, parameter))

    def test_hash_parameter_steps_include_whitespace_validation(self) -> None:
        steps = _hash_parameter_steps(
            {"request_example": {"hash": "hash-value"}},
            {"name": "Hash", "type": "String"},
            "BAD_REQUEST",
            "{}",
        )
        self.assertEqual(
            [step["step"].split("\n", 1)[0] for step in steps],
            [
                "Hash doesn't set",
                "Hash leave blank",
                "Hash input space",
                "Hash input int",
            ],
        )
        self.assertEqual(steps[2]["step"].split("\n", 1)[1], '"Hash": " hash-value "')

    def test_user_id_has_one_documented_whitespace_step(self) -> None:
        steps = _parameter_steps(
            {"error_codes": [{"code": "309", "context": "Unknown UserID"}]},
            {"request_example": {"userId": "1e9lqcg8ddui"}},
            {"name": "userId", "type": "String", "required": "Y"},
            {"code": "BAD_REQUEST"},
        )
        whitespace_steps = [
            step for step in steps if step["step"].startswith("userId input space")
        ]
        self.assertEqual(len(whitespace_steps), 1)
        self.assertIn('"userId": " 1e9lqcg8ddui "', whitespace_steps[0]["step"])
        self.assertIn("error code 309", whitespace_steps[0]["expected"])

    def test_pipe_amount_parameters_validate_amount_segment(self) -> None:
        steps = _parameter_steps(
            {},
            {"request_example": {"bet": "2000|txn-001"}},
            {
                "name": "bet",
                "type": "String",
                "required": "Y",
                "description": "Amount in cents and transactionId in format: bet_amount | transactionId",
                "remark": "bet_amount and transactionId are separated by |.",
            },
            {"code": "610"},
        )
        titles = [step["step"].split("\n", 1)[0] for step in steps]
        self.assertEqual(
            titles[-4:],
            [
                "bet amount doesn't set",
                "bet amount input string",
                "bet amount input negative number",
                "bet amount input decimal",
            ],
        )
        self.assertIn('"bet": "|txn-001"', steps[-4]["step"])
        self.assertIn('"bet": "-1|txn-001"', steps[-2]["step"])

    def test_compiles_explicit_rules_without_vendor_hardcode(self) -> None:
        endpoints = [
            {
                "endpoint": "/v1/cancel",
                "section": "Cancel",
                "request_parameters": [
                    {"name": "mode", "type": "String", "required": "Y"},
                    {
                        "name": "referenceId",
                        "type": "String",
                        "required": "Y/N",
                        "remark": (
                            "Dependency: when mode in [A,B] => Y; "
                            "when mode = C => N(omit); error=BAD_REQUEST"
                        ),
                    },
                ],
            }
        ]
        profile, report = compile_parameter_dependencies(
            endpoints, [{"code": "BAD_REQUEST", "context": "invalid request"}]
        )
        self.assertTrue(report["valid"])
        self.assertTrue(endpoints[0]["parameter_dependency"])
        self.assertEqual(profile["endpoints"][0]["selectors"], ["mode"])
        self.assertEqual(len(profile["endpoints"][0]["rules"]), 2)
        self.assertEqual(profile["endpoints"][0]["rules"][1]["field_state"], "forbidden")

    def test_invalid_selector_fails_closed_for_endpoint(self) -> None:
        endpoints = [
            {
                "endpoint": "/v1/test",
                "request_parameters": [
                    {
                        "name": "value",
                        "required": "Y/N",
                        "remark": "Dependency: when missing = A => Y; otherwise => N(optional); error=BAD_REQUEST",
                    }
                ],
            }
        ]
        profile, report = compile_parameter_dependencies(endpoints, [{"code": "BAD_REQUEST"}])
        self.assertFalse(report["valid"])
        self.assertFalse(profile["endpoints"][0]["enabled"])
        self.assertEqual(profile["endpoints"][0]["rules"], [])

    def test_requires_explicit_error_code(self) -> None:
        endpoints = [
            {
                "endpoint": "/v1/test",
                "request_parameters": [
                    {"name": "kind", "required": "Y"},
                    {
                        "name": "value",
                        "required": "Y/N",
                        "remark": "Dependency: when kind = A => Y; otherwise => N(omit)",
                    },
                ],
            }
        ]
        _, report = compile_parameter_dependencies(endpoints, [{"code": "BAD_REQUEST"}])
        self.assertFalse(report["valid"])
        self.assertIn("error=<ERROR_CODE>", report["errors"][0]["message"])

    def test_compiles_human_required_optional_blocks(self) -> None:
        endpoints = [
            {
                "endpoint": "/v1/win",
                "request_parameters": [
                    {"name": "winType", "required": "Y"},
                    {
                        "name": "rewardId",
                        "required": "Y/N",
                        "remark": (
                            "Required when:\n"
                            "winType = WIN_FREE\n"
                            "Optional when:\n"
                            "winType = WIN_ORDINARY\n"
                            "winType = WIN_JACKPOT"
                        ),
                    },
                ],
            }
        ]
        profile, report = compile_parameter_dependencies(
            endpoints, [{"code": "BAD_REQUEST"}]
        )
        endpoint = profile["endpoints"][0]
        self.assertTrue(report["valid"])
        self.assertTrue(endpoint["enabled"])
        self.assertEqual(len(endpoint["rules"]), 3)
        self.assertEqual(
            [rule["field_state"] for rule in endpoint["rules"]],
            ["required", "optional", "optional"],
        )

    def test_infers_unique_selector_from_documented_enum_owner(self) -> None:
        endpoints = [
            {
                "endpoint": "/v1/cancel",
                "request_parameters": [
                    {
                        "name": "cancelType",
                        "required": "Y",
                        "description": (
                            "Allowed values: CANCEL_BET, CANCEL_ROUND, CANCEL_TRANSACTION"
                        ),
                    },
                    {
                        "name": "isAdjustment",
                        "required": "Y/N",
                        "remark": (
                            "Require when\nCANCEL_BET\n"
                            "Optional when\nCANCEL_ROUND\nCANCEL_TRANSACTION"
                        ),
                    },
                ],
            }
        ]
        profile, report = compile_parameter_dependencies(
            endpoints, [{"code": "BAD_REQUEST"}]
        )
        endpoint = profile["endpoints"][0]
        self.assertTrue(report["valid"])
        self.assertTrue(endpoint["enabled"])
        self.assertEqual(endpoint["selectors"], ["cancelType"])
        self.assertTrue(
            all(
                rule["selector_source"] == "unique_enum_value_owner"
                for rule in endpoint["rules"]
            )
        )

    def test_compiles_complete_cancel_dependency_chain_from_remarks(self) -> None:
        endpoints = [
            {
                "endpoint": "/v1/cancel",
                "request_parameters": [
                    {
                        "name": "cancelType",
                        "required": "Y",
                        "description": (
                            "The type may be one of the following values: "
                            "CANCEL_ROUND, CANCEL_BET, CANCEL_TRANSACTION"
                        ),
                    },
                    {
                        "name": "refTransactionId",
                        "required": "Y/N",
                        "remark": (
                            "Required when:\nCANCEL_BET\nCANCEL_TRANSACTION\n"
                            "Optional when:\nCANCEL_ROUND"
                        ),
                    },
                    {
                        "name": "adjustmentRefund",
                        "required": "Y/N",
                        "remark": (
                            "Require when:\nisAdjustment = true\n"
                            "Optional when:\nisAdjustment = false"
                        ),
                    },
                    {
                        "name": "adjustmentRefund/amount",
                        "required": "Y/N",
                        "remark": (
                            "Require when:\nisAdjustment = true\n"
                            "Optional when:\nisAdjustment = false"
                        ),
                    },
                    {
                        "name": "adjustmentRefund/currency",
                        "required": "Y/N",
                        "remark": (
                            "Require when:\nisAdjustment = true\n"
                            "Optional when:\nisAdjustment = false"
                        ),
                    },
                    {
                        "name": "isAdjustment",
                        "required": "Y/N",
                        "remark": (
                            "Require when:\nCANCEL_BET\nOptional when:\n"
                            "CANCEL_ROUND\nCANCEL_TRANSACTION"
                        ),
                    },
                ],
            }
        ]
        profile, report = compile_parameter_dependencies(
            endpoints, [{"code": "BAD_REQUEST"}]
        )
        endpoint = profile["endpoints"][0]
        self.assertTrue(report["valid"])
        self.assertTrue(endpoint["enabled"])
        self.assertEqual(endpoint["selectors"], ["cancelType", "isAdjustment"])
        self.assertEqual(
            endpoint["affected_parameters"],
            [
                "adjustmentRefund",
                "adjustmentRefund.amount",
                "adjustmentRefund.currency",
                "isAdjustment",
                "refTransactionId",
            ],
        )
        rules_by_field = {}
        for rule in endpoint["rules"]:
            rules_by_field.setdefault(rule["affected_field"], []).append(rule)
        self.assertEqual(len(rules_by_field["refTransactionId"]), 3)
        self.assertEqual(len(rules_by_field["isAdjustment"]), 3)
        for field in (
            "adjustmentRefund",
            "adjustmentRefund.amount",
            "adjustmentRefund.currency",
        ):
            self.assertEqual(
                [rule["when"]["field"] for rule in rules_by_field[field]],
                ["isAdjustment", "isAdjustment"],
            )
            self.assertEqual(
                [rule["field_state"] for rule in rules_by_field[field]],
                ["required", "optional"],
            )


class ParameterDependencyGeneratorTests(unittest.TestCase):
    def test_path_parameter_is_not_duplicated_by_request_table(self) -> None:
        endpoint = {
            "endpoint": "/v1/sessions/{sessionId}",
            "role": "authentication",
            "request_parameters": [
                {"name": "sessionId", "type": "string", "required": "Y"},
            ],
            "error_response_example": {"code": "INVALID_REQUEST", "message": "Invalid sessionId"},
        }
        context = {
            "endpoint_roles": [endpoint],
            "parameter_error": {"code": "INVALID_REQUEST", "source": "documented"},
            "case_authoring_rules": {"default_game_code": "GAME"},
            "default_test_account": "account",
        }

        cases = _parameter_validation_cases(context, [])

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["parameter"], "sessionId")
        self.assertEqual(cases[0]["endpoint_name"], "sessions")

    def test_operation_variants_generate_separate_parameter_groups(self) -> None:
        endpoint = {
            "endpoint": "/v1/transactions",
            "role": "supporting_endpoint",
            "operation_variants": [
                {
                    "operation": "BET",
                    "request_parameters": [
                        {"name": "betId", "type": "string", "required": "Y"},
                    ],
                    "request_example": {"betId": "bet-1"},
                    "error_response_example": {"code": "INVALID_REQUEST", "message": "Invalid betId"},
                },
                {
                    "operation": "WIN",
                    "request_parameters": [
                        {"name": "winId", "type": "string", "required": "Y"},
                        {"name": "details", "type": "object", "required": "N"},
                        {"name": "details/id", "type": "string", "required": "Y"},
                    ],
                    "request_example": {"winId": "win-1"},
                    "error_response_example": {"code": "INVALID_REQUEST", "message": "Invalid winId"},
                },
            ],
        }
        context = {
            "endpoint_roles": [endpoint],
            "parameter_error": {"code": "INVALID_REQUEST", "source": "documented"},
            "case_authoring_rules": {"default_game_code": "GAME"},
            "default_test_account": "account",
        }

        cases = _parameter_validation_cases(context, [])

        self.assertEqual(
            [case["parameter"] for case in cases],
            ["betId", "winId", "details", "details/id"],
        )
        self.assertEqual(
            [case["endpoint_name"] for case in cases],
            [
                "transactions - BET",
                "transactions - WIN",
                "transactions - WIN",
                "transactions - WIN",
            ],
        )
        self.assertEqual(
            [case["endpoint_operation"] for case in cases],
            ["BET", "WIN", "WIN", "WIN"],
        )
        details_case = next(case for case in cases if case["parameter"] == "details")
        self.assertIn('{"id": "<confirm details/id>"}', details_case["steps"][0]["step"])

    def test_affected_parameter_uses_dependency_cases_and_unaffected_stays_standard(self) -> None:
        endpoint = {
            "endpoint": "/v1/cancel",
            "role": "cancel_bet",
            "request_parameters": [
                {"name": "mode", "type": "String", "required": "Y"},
                {"name": "referenceId", "type": "String", "required": "Y/N"},
            ],
            "request_example": {"mode": "A", "referenceId": "ref-1"},
            "success_response_example": {"error": "OK"},
            "error_response_example": {"error": "BAD_REQUEST"},
            "parameter_dependency": True,
            "dependency_affected_parameters": ["referenceId"],
            "parameter_dependencies": [
                {
                    "rule_id": "cancel.reference.1",
                    "when": {"field": "mode", "operator": "eq", "value": "A"},
                    "affected_field": "referenceId",
                    "field_state": "required",
                    "error_code": "BAD_REQUEST",
                },
                {
                    "rule_id": "cancel.reference.2",
                    "when": {"field": "mode", "operator": "eq", "value": "C"},
                    "affected_field": "referenceId",
                    "field_state": "forbidden",
                    "error_code": "BAD_REQUEST",
                },
            ],
        }
        context = {
            "endpoint_roles": [endpoint],
            "parameter_error": {"code": "BAD_REQUEST", "source": "documented"},
            "case_authoring_rules": {"default_game_code": "GAME"},
            "default_test_account": "account",
        }
        cases = _parameter_validation_cases(context, [])
        standard = [case for case in cases if case["category"] == "parameter_validation"]
        dependency = [
            case for case in cases if case["category"] == "parameter_dependency_validation"
        ]
        self.assertEqual([case["parameter"] for case in standard], ["mode"])
        self.assertEqual(len(dependency), 2)
        self.assertEqual(
            {case["dependency_case_kind"] for case in dependency},
            {"required_validation", "forbidden_validation"},
        )
        required_case = next(
            case for case in dependency
            if case["dependency_case_kind"] == "required_validation"
        )
        self.assertEqual(
            required_case["scenario"],
            "case：check the referenceId validation when mode=A",
        )
        self.assertTrue(required_case["steps"][0]["step"].startswith("referenceId doesn't set\n"))
        self.assertNotIn("Set dependency context", required_case["steps"][0]["step"])

    def test_nested_dependency_payloads_and_type_steps_are_context_aware(self) -> None:
        parameters = [
            {"name": "isAdjustment", "type": "boolean", "required": "Y/N"},
            {"name": "adjustmentRefund", "type": "object", "required": "Y/N"},
            {"name": "adjustmentRefund/amount", "type": "decimal", "required": "Y/N"},
            {"name": "adjustmentRefund/currency", "type": "string", "required": "Y/N"},
        ]
        rules = []
        for field in (
            "adjustmentRefund",
            "adjustmentRefund.amount",
            "adjustmentRefund.currency",
        ):
            for index, (value, state) in enumerate(
                (("true", "required"), ("false", "optional")), start=1
            ):
                rules.append(
                    {
                        "rule_id": f"cancel.{field}.{index}",
                        "when": {
                            "field": "isAdjustment",
                            "operator": "eq",
                            "value": value,
                        },
                        "affected_field": field,
                        "field_state": state,
                        "error_code": "BAD_REQUEST",
                    }
                )
        endpoint = {
            "endpoint": "/v1/cancel",
            "role": "cancel_bet",
            "request_parameters": parameters,
            "request_example": {"isAdjustment": True},
            "success_response_example": {"status": "OK"},
            "error_response_example": {"error": "BAD_REQUEST"},
            "parameter_dependency": True,
            "dependency_affected_parameters": [
                "adjustmentRefund",
                "adjustmentRefund.amount",
                "adjustmentRefund.currency",
            ],
            "parameter_dependencies": rules,
        }
        context = {
            "endpoint_roles": [endpoint],
            "parameter_error": {"code": "BAD_REQUEST", "source": "documented"},
            "case_authoring_rules": {"default_game_code": "GAME"},
            "default_test_account": "account",
        }
        cases = _parameter_validation_cases(context, [])
        dependency = [
            case for case in cases if case["category"] == "parameter_dependency_validation"
        ]

        optional_parent = next(
            case
            for case in dependency
            if case["parameter"] == "adjustmentRefund"
            and case["dependency_case_kind"] == "optional_validation"
        )
        self.assertGreaterEqual(len(optional_parent["steps"]), 2)
        self.assertIn(
            '"adjustmentRefund": {"amount": 100.0, "currency": "EUR"}',
            optional_parent["steps"][0]["step"],
        )

        for field in ("adjustmentRefund.amount", "adjustmentRefund.currency"):
            contextual = [
                case
                for case in dependency
                if case["parameter"] == field
            ]
            self.assertEqual(len(contextual), 2)
            self.assertEqual(
                {case["dependency_case_kind"] for case in contextual},
                {"required_validation", "optional_validation"},
            )
            all_step_text = "\n".join(
                step["step"] for case in contextual for step in case["steps"]
            )
            self.assertNotIn("adjustmentRefund/", all_step_text)
            self.assertIn('"adjustmentRefund": {', all_step_text)
            self.assertNotIn("Set dependency context", all_step_text)

        currency_contextual = [
            case
            for case in dependency
            if case["parameter"] == "adjustmentRefund.currency"
        ]
        currency_steps = "\n".join(
            step["step"] for case in currency_contextual for step in case["steps"]
        )
        self.assertIn("Input invalid currency", currency_steps)
        self.assertFalse(
            any("(intrinsic validation)" in case["scenario"] for case in dependency)
        )


if __name__ == "__main__":
    unittest.main()
