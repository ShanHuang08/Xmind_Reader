"""Schema constants for draft test case generation contracts."""

from __future__ import annotations

from typing import Any

from generator.user_behavior_mapping import (
    CANONICAL_USER_BEHAVIOR_LEAF_SECTIONS,
    KNOWLEDGE_CATEGORY_TO_XMIND_SECTION,
)


SCHEMA_VERSION = "draft-test-cases/v1"

PRECONDITIONS_LABEL = "前置条件："
REMARKS_LABEL = "备注："

CASE_TITLE_PREFIX = "case："
API_PARAMETER_TEST_SECTION = "API parameter test"
API_PARAMETER_CASE_TITLE_TEMPLATE = "case：check the {parameter} validation"

XMIND_CASE_FIELD_LABELS = {
    "case_title_prefix": CASE_TITLE_PREFIX,
    "preconditions": PRECONDITIONS_LABEL,
    "module": "所属模块：",
    "labels": "标签：",
    "remarks": REMARKS_LABEL,
    "priority": "用例等级：",
    "steps_root": "步骤描述：",
    "step": "步骤：",
    "expected": "预期结果：",
}

API_PARAMETER_TEST_CONTRACT = {
    "section": API_PARAMETER_TEST_SECTION,
    "hierarchy": [
        "API parameter test",
        "<endpoint name from parsed endpoints>",
        "case：check the {parameter} validation",
    ],
    "required_case_fields": [
        "output_section",
        "category",
        "endpoint",
        "parameter",
        "scenario",
        "preconditions",
        "steps",
        "remarks",
    ],
    "scenario_template": API_PARAMETER_CASE_TITLE_TEMPLATE,
    "language": "zh-CN for XMind case field labels. Step and expected result content after the label should be English.",
    "routing": {
        "xmind_level_1": "API parameter test",
        "xmind_level_2": "endpoint_name",
        "xmind_case_title": "scenario",
    },
}

ALLOWED_OUTPUT_SECTIONS = {
    "API parameter test",
    *CANONICAL_USER_BEHAVIOR_LEAF_SECTIONS,
}

CAPABILITY_CATEGORY_VARIANTS = {
    "multiple_bets": [
        {
            "category": "multiple_bets_one_bet_endpoint",
            "template_variant": "one_bet_endpoint",
            "description": (
                "Use when the vendor performs multiple bets through the same bet endpoint. "
                "The endpoint may use an action/method parameter or repeated requests with the same round context."
            ),
            "applicability": {
                "required_capabilities": ["multiple_bets"],
                "endpoint_topology": "one_bet_endpoint",
            },
        },
        {
            "category": "multiple_bets_two_bet_endpoint",
            "template_variant": "two_bet_endpoint",
            "description": (
                "Use when the vendor performs multiple bets through two separated bet-like endpoints, "
                "such as Bet and Rebet."
            ),
            "applicability": {
                "required_capabilities": ["multiple_bets"],
                "endpoint_topology": "two_bet_endpoint",
            },
        },
    ],
    "bet_and_settle": [
        {
            "category": "bet_and_settle_has_round_end_control_parameter",
            "template_variant": "has_round_end_control_parameter",
            "description": (
                "Use when a combined bet-and-settlement endpoint exists and has a parameter that controls round completion."
            ),
            "applicability": {
                "required_endpoint_roles": ["combined_bet_settlement"],
                "required_parameter_semantics": ["combined_bet_settlement", "round_end_control"],
                "parameter_semantics": {
                    "combined_bet_settlement": True,
                    "round_end_control": True,
                },
            },
        },
    ],
    "multiple_settlements": [
        {
            "category": "multiple_settlements_has_round_end_control_parameter",
            "template_variant": "has_round_end_control_parameter",
            "description": (
                "Use when the settlement/result endpoint has a parameter that controls whether the round is complete."
            ),
            "applicability": {
                "required_capabilities": ["multiple_settlements"],
                "required_endpoint_roles": ["settlement"],
                "required_parameter_semantics": ["round_end_control"],
                "parameter_semantics": {"round_end_control": True},
            },
        },
        {
            "category": "multiple_settlements_no_round_end_control_parameter",
            "template_variant": "no_round_end_control_parameter",
            "description": (
                "Use when multiple settlements are supported but the settlement/result endpoint has no round-end control parameter."
            ),
            "applicability": {
                "required_capabilities": ["multiple_settlements"],
                "required_endpoint_roles": ["settlement"],
                "parameter_semantics": {"round_end_control": False},
            },
        },
    ],
}

CONDITIONAL_MANDATORY_CATEGORIES = {
    "authenticate": {
        "category": "authenticate",
        "output_section": "User Behavior > Launch Game",
        "condition": "endpoint_analysis.endpoint_topology.authenticate.mode == endpoint_present",
    },
    "authentication_is_necessary": {
        "category": "authentication_is_necessary",
        "output_section": "User Behavior > Bet and Settle",
        "condition": (
            "endpoint_analysis.endpoint_topology.authenticate.mode == endpoint_present "
            "and endpoint_analysis.endpoint_topology.authenticate.authentication_required == true"
        ),
    },
    "bet_and_settle": {
        "category": "bet_and_settle",
        "output_section": "User Behavior > Bet and Settle",
        "condition": "endpoint_analysis.endpoint_topology.bet_and_settle.mode == combined_endpoint",
    },
    "bet_and_settle_has_round_end_control_parameter": {
        "category": "bet_and_settle_has_round_end_control_parameter",
        "output_section": "User Behavior > Bet and Settle",
        "condition": (
            "endpoint_analysis.endpoint_topology.bet_and_settle.mode == combined_endpoint "
            "and endpoint_analysis.parameter_semantics.round_end_control == true"
        ),
    },
}

REQUIRED_DRAFT_FIELDS = (
    "schema_version",
    "vendor",
    "capability_profile",
    "endpoint_roles",
    "generation_mapping",
    "test_cases",
)

REQUIRED_TEST_CASE_FIELDS = (
    "output_section",
    "category",
    "scenario",
    "preconditions",
    "steps",
    "remarks",
)

OPTIONAL_TEST_CASE_FIELDS = (
    "id",
    "module",
    "source_capability",
    "reference_cases",
    "endpoint",
    "endpoint_name",
    "endpoint_group",
    "template_variant",
    "applicability",
    "behavior_flow",
    "required_endpoint_roles",
    "required_parameter_semantics",
    "endpoint_analysis",
    "endpoints",
    "parameter",
    "tags",
    "priority",
    "expected_error",
    "source_reference",
    "unresolved_questions",
)

EXPECTED_ERROR_REQUIRED_FIELDS = ("code", "source")

INFERRED_ERROR_SOURCES = {
    "inferred",
    "inferred_from_limited_vendor_codes",
    "inferred_from_endpoint_codes",
    "inferred_from_vendor_codes",
}

NEGATIVE_KEYWORDS = (
    "fail",
    "failed",
    "failure",
    "reject",
    "rejected",
    "error",
    "invalid",
    "missing",
    "duplicate",
    "timeout",
    "not found",
    "exceed",
    "negative",
    "失敗",
    "錯誤",
    "异常",
    "異常",
    "失败",
    "错误",
    "拒绝",
    "无效",
    "缺少",
    "重复",
    "拒絕",
    "無效",
    "缺少",
    "重複",
)


def schema_summary() -> dict[str, Any]:
    """Return a JSON-serializable summary for docs, prompts, and reports."""
    return {
        "schema_version": SCHEMA_VERSION,
        "required_draft_fields": list(REQUIRED_DRAFT_FIELDS),
        "required_test_case_fields": list(REQUIRED_TEST_CASE_FIELDS),
        "optional_test_case_fields": list(OPTIONAL_TEST_CASE_FIELDS),
        "id_rule": "Optional before MeterSphere upload. If present, ids must be unique.",
        "preconditions_label": PRECONDITIONS_LABEL,
        "remarks_label": REMARKS_LABEL,
        "xmind_case_field_labels": XMIND_CASE_FIELD_LABELS,
        "api_parameter_test_contract": API_PARAMETER_TEST_CONTRACT,
        "allowed_output_sections": sorted(ALLOWED_OUTPUT_SECTIONS),
        "knowledge_category_to_xmind_section": KNOWLEDGE_CATEGORY_TO_XMIND_SECTION,
        "capability_category_variants": CAPABILITY_CATEGORY_VARIANTS,
        "conditional_mandatory_categories": CONDITIONAL_MANDATORY_CATEGORIES,
        "expected_error_required_fields": list(EXPECTED_ERROR_REQUIRED_FIELDS),
        "inferred_error_sources": sorted(INFERRED_ERROR_SOURCES),
    }
