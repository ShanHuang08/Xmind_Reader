"""Schema constants for draft test case generation contracts."""

from __future__ import annotations

from typing import Any


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
    "User Behavior > Launch Game",
    "User Behavior > Get Player balance",
    "User Behavior > Bet and Settle",
    "User Behavior > Cancel Bet",
    "User Behavior > Game type > Slots",
    "User Behavior > Game type > Arcade game",
    "User Behavior > Game type > Mini game",
    "User Behavior > Game type > Crash game",
}

KNOWLEDGE_CATEGORY_TO_XMIND_SECTION = {
    "parameter_validation": "API parameter test",
    "launch_game": "User Behavior > Launch Game",
    "authenticate": "User Behavior > Launch Game",
    "balance": "User Behavior > Get Player balance",
    "bet": "User Behavior > Bet and Settle",
    "settlement": "User Behavior > Bet and Settle",
    "amount_precision": "User Behavior > Bet and Settle",
    "multiple_bets": "User Behavior > Bet and Settle",
    "multiple_settlements": "User Behavior > Bet and Settle",
    "modify_settlement_adjustment": "User Behavior > Bet and Settle",
    "settle_by_round_or_settle_by_bet": "User Behavior > Bet and Settle",
    "bet_and_settle": "User Behavior > Bet and Settle",
    "betandsettle": "User Behavior > Bet and Settle",
    "idempotency": "User Behavior > Bet and Settle",
    "rollback": "User Behavior > Cancel Bet",
    "rollback_bet": "User Behavior > Cancel Bet",
    "rollback_settled_bet": "User Behavior > Cancel Bet",
    "rollback_by_round_or_rollback_by_bet": "User Behavior > Cancel Bet",
    "rollback_bet_and_settle": "User Behavior > Cancel Bet",
    "rollback_betandsettle": "User Behavior > Cancel Bet",
    "freespin": "User Behavior > Bet and Settle",
    "jackpot": "User Behavior > Bet and Settle",
    "slots": "User Behavior > Game type > Slots",
    "arcade_game": "User Behavior > Game type > Arcade game",
    "mini_game": "User Behavior > Game type > Mini game",
    "crash_game": "User Behavior > Game type > Crash game",
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
        "expected_error_required_fields": list(EXPECTED_ERROR_REQUIRED_FIELDS),
        "inferred_error_sources": sorted(INFERRED_ERROR_SOURCES),
    }
