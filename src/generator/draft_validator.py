"""Validate draft_test_cases.json before XMind writing."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from generator.draft_schema import (
        ALLOWED_OUTPUT_SECTIONS,
        API_PARAMETER_CASE_TITLE_TEMPLATE,
        API_PARAMETER_TEST_SECTION,
        EXPECTED_ERROR_REQUIRED_FIELDS,
        INFERRED_ERROR_SOURCES,
        KNOWLEDGE_CATEGORY_TO_XMIND_SECTION,
        NEGATIVE_KEYWORDS,
        PRECONDITIONS_LABEL,
        REMARKS_LABEL,
        REQUIRED_DRAFT_FIELDS,
        REQUIRED_TEST_CASE_FIELDS,
        SCHEMA_VERSION,
    )
except ModuleNotFoundError:  # pragma: no cover - supports python -m src.generator...
    from .draft_schema import (
        ALLOWED_OUTPUT_SECTIONS,
        API_PARAMETER_CASE_TITLE_TEMPLATE,
        API_PARAMETER_TEST_SECTION,
        EXPECTED_ERROR_REQUIRED_FIELDS,
        INFERRED_ERROR_SOURCES,
        KNOWLEDGE_CATEGORY_TO_XMIND_SECTION,
        NEGATIVE_KEYWORDS,
        PRECONDITIONS_LABEL,
        REMARKS_LABEL,
        REQUIRED_DRAFT_FIELDS,
        REQUIRED_TEST_CASE_FIELDS,
        SCHEMA_VERSION,
    )


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [issue.as_dict() for issue in self.errors],
            "warnings": [issue.as_dict() for issue in self.warnings],
        }


def validate_draft_file(path: Path | str) -> ValidationResult:
    """Read and validate a draft JSON file."""
    draft_path = Path(path)
    with draft_path.open(encoding="utf-8") as file:
        draft = json.load(file)
    return validate_draft(draft)


def validate_draft(draft: dict[str, Any]) -> ValidationResult:
    """Validate a draft JSON object against the generation contract."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if not isinstance(draft, dict):
        return ValidationResult(
            valid=False,
            errors=[_error("$", "Draft root must be a JSON object.")],
            warnings=[],
        )

    _validate_root(draft, errors, warnings)
    test_cases = draft.get("test_cases", [])
    if isinstance(test_cases, list):
        _validate_test_cases(test_cases, errors, warnings)

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


def _validate_root(
    draft: dict[str, Any], errors: list[ValidationIssue], warnings: list[ValidationIssue]
) -> None:
    for field in REQUIRED_DRAFT_FIELDS:
        if field not in draft:
            errors.append(_error(f"$.{field}", "Required draft field is missing."))

    schema_version = draft.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        errors.append(
            _error(
                "$.schema_version",
                f"Expected schema_version {SCHEMA_VERSION!r}, got {schema_version!r}.",
            )
        )

    if "test_cases" in draft and not isinstance(draft.get("test_cases"), list):
        errors.append(_error("$.test_cases", "test_cases must be a list."))

    generation_mapping = draft.get("generation_mapping", {})
    if generation_mapping and not isinstance(generation_mapping, dict):
        errors.append(_error("$.generation_mapping", "generation_mapping must be an object."))
        return

    mapping = generation_mapping.get("knowledge_category_to_xmind_section", {})
    if mapping and not isinstance(mapping, dict):
        errors.append(
            _error(
                "$.generation_mapping.knowledge_category_to_xmind_section",
                "knowledge_category_to_xmind_section must be an object.",
            )
        )
        return

    for category, expected_section in KNOWLEDGE_CATEGORY_TO_XMIND_SECTION.items():
        actual_section = mapping.get(category)
        if actual_section is None:
            warnings.append(
                _warning(
                    f"$.generation_mapping.knowledge_category_to_xmind_section.{category}",
                    "Recommended category mapping is missing.",
                )
            )
        elif actual_section != expected_section:
            errors.append(
                _error(
                    f"$.generation_mapping.knowledge_category_to_xmind_section.{category}",
                    f"Expected {expected_section!r}, got {actual_section!r}.",
                )
            )


def _validate_test_cases(
    test_cases: list[Any], errors: list[ValidationIssue], warnings: list[ValidationIssue]
) -> None:
    seen_ids: dict[str, int] = {}
    for index, test_case in enumerate(test_cases):
        path = f"$.test_cases[{index}]"
        if not isinstance(test_case, dict):
            errors.append(_error(path, "Test case must be an object."))
            continue

        for field in REQUIRED_TEST_CASE_FIELDS:
            if _is_empty(test_case.get(field)):
                errors.append(_error(f"{path}.{field}", "Required test case field is missing."))

        case_id = str(test_case.get("id", "")).strip()
        if case_id:
            if case_id in seen_ids:
                first_index = seen_ids[case_id]
                errors.append(
                    _error(
                        f"{path}.id",
                        f"Duplicate id {case_id!r}; first used at $.test_cases[{first_index}].id.",
                    )
                )
            else:
                seen_ids[case_id] = index

        _validate_output_section(test_case, path, errors)
        _validate_api_parameter_case(test_case, path, errors, warnings)
        _validate_labels(test_case, path, errors)
        _validate_steps(test_case, path, errors)
        _validate_simplified_case_labels(test_case, path, warnings)
        _validate_expected_error(test_case, path, errors, warnings)
        _validate_source_reference(test_case, path, warnings)


def _validate_output_section(
    test_case: dict[str, Any], path: str, errors: list[ValidationIssue]
) -> None:
    output_section = test_case.get("output_section", "")
    category = test_case.get("category", "")
    if output_section and output_section not in ALLOWED_OUTPUT_SECTIONS:
        errors.append(
            _error(
                f"{path}.output_section",
                f"Unknown output_section {output_section!r}.",
            )
        )

    expected_section = KNOWLEDGE_CATEGORY_TO_XMIND_SECTION.get(category)
    if expected_section and output_section and output_section != expected_section:
        errors.append(
            _error(
                f"{path}.output_section",
                f"Category {category!r} must route to {expected_section!r}.",
            )
        )


def _validate_api_parameter_case(
    test_case: dict[str, Any],
    path: str,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    output_section = test_case.get("output_section", "")
    category = test_case.get("category", "")
    is_parameter_case = (
        output_section == API_PARAMETER_TEST_SECTION or category == "parameter_validation"
    )
    if not is_parameter_case:
        return

    endpoint = str(test_case.get("endpoint", "")).strip()
    parameter = str(test_case.get("parameter", "")).strip()
    scenario = str(test_case.get("scenario", "")).strip()

    if not endpoint:
        errors.append(
            _error(
                f"{path}.endpoint",
                "API parameter test cases must include the parsed endpoint name.",
            )
        )
    if not parameter:
        errors.append(
            _error(
                f"{path}.parameter",
                "API parameter test cases must include the request parameter name.",
            )
        )
        return

    expected_scenario = API_PARAMETER_CASE_TITLE_TEMPLATE.format(parameter=parameter)
    if scenario and scenario != expected_scenario:
        human_overrides = test_case.get("human_overrides", [])
        if isinstance(human_overrides, list) and "scenario" in human_overrides:
            warnings.append(
                _warning(
                    f"{path}.scenario",
                    f"Human-edited API parameter case scenario differs from {expected_scenario!r}.",
                )
            )
        else:
            errors.append(
                _error(
                    f"{path}.scenario",
                    f"API parameter case scenario must be {expected_scenario!r}.",
                )
            )

    expected_module = str(test_case.get("endpoint_name") or endpoint.rsplit("/", 1)[-1]).strip()
    if test_case.get("module") and expected_module and test_case.get("module") != expected_module:
        warnings.append(
            _warning(
                f"{path}.module",
                f"API parameter test cases usually use module {expected_module!r}.",
            )
        )


def _validate_labels(
    test_case: dict[str, Any], path: str, errors: list[ValidationIssue]
) -> None:
    preconditions = test_case.get("preconditions")
    if isinstance(preconditions, str) and not preconditions.strip().startswith(PRECONDITIONS_LABEL):
        errors.append(
            _error(
                f"{path}.preconditions",
                f"preconditions must start with {PRECONDITIONS_LABEL!r}.",
            )
        )

    remarks = test_case.get("remarks")
    if isinstance(remarks, str) and not remarks.strip().startswith(REMARKS_LABEL):
        errors.append(
            _error(f"{path}.remarks", f"remarks must start with {REMARKS_LABEL!r}.")
        )


def _validate_steps(test_case: dict[str, Any], path: str, errors: list[ValidationIssue]) -> None:
    steps = test_case.get("steps")
    if not isinstance(steps, list):
        if steps is not None:
            errors.append(_error(f"{path}.steps", "steps must be a non-empty list."))
        return
    if not steps:
        errors.append(_error(f"{path}.steps", "steps must not be empty."))
        return

    for step_index, step in enumerate(steps):
        step_path = f"{path}.steps[{step_index}]"
        if not isinstance(step, dict):
            errors.append(_error(step_path, "Each step must be an object."))
            continue
        if _is_empty(step.get("step")):
            errors.append(_error(f"{step_path}.step", "Step text is required."))
        if _is_empty(step.get("expected")):
            errors.append(_error(f"{step_path}.expected", "Expected result is required."))


def _validate_simplified_case_labels(
    test_case: dict[str, Any], path: str, warnings: list[ValidationIssue]
) -> None:
    traditional_labels = (
        "前置條件",
        "備註",
        "步驟",
        "預期結果",
        "標籤",
        "所屬模組",
        "用例等級",
    )
    fields = [
        ("scenario", test_case.get("scenario", "")),
        ("preconditions", test_case.get("preconditions", "")),
        ("remarks", test_case.get("remarks", "")),
    ]
    for step_index, step in enumerate(test_case.get("steps", []) or []):
        if isinstance(step, dict):
            fields.append((f"steps[{step_index}].step", step.get("step", "")))
            fields.append((f"steps[{step_index}].expected", step.get("expected", "")))

    for field, value in fields:
        text = str(value)
        matched = [label for label in traditional_labels if label in text]
        if matched:
            warnings.append(
                _warning(
                    f"{path}.{field}",
                    "Use Simplified Chinese XMind labels instead of Traditional labels: "
                    + ", ".join(matched),
                )
            )


def _validate_expected_error(
    test_case: dict[str, Any],
    path: str,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    expected_error = test_case.get("expected_error")
    is_negative = _looks_negative(test_case)

    if is_negative and _is_empty(expected_error):
        errors.append(
            _error(
                f"{path}.expected_error",
                "Failure or negative cases must include expected_error.",
            )
        )
        return

    if _is_empty(expected_error):
        return

    if not isinstance(expected_error, dict):
        errors.append(_error(f"{path}.expected_error", "expected_error must be an object."))
        return

    for field in EXPECTED_ERROR_REQUIRED_FIELDS:
        if _is_empty(expected_error.get(field)):
            errors.append(
                _error(f"{path}.expected_error.{field}", "Expected error field is required.")
            )

    source = str(expected_error.get("source", "")).strip()
    if source in INFERRED_ERROR_SOURCES and _is_empty(expected_error.get("inference_reason")):
        warnings.append(
            _warning(
                f"{path}.expected_error.inference_reason",
                "Inferred error codes should include inference_reason for review.",
            )
        )


def _validate_source_reference(
    test_case: dict[str, Any], path: str, warnings: list[ValidationIssue]
) -> None:
    source_reference = test_case.get("source_reference")
    if _is_empty(source_reference):
        warnings.append(
            _warning(
                f"{path}.source_reference",
                "source_reference is recommended for traceability.",
            )
        )
        return
    if not isinstance(source_reference, dict):
        warnings.append(_warning(f"{path}.source_reference", "source_reference should be an object."))


def _looks_negative(test_case: dict[str, Any]) -> bool:
    fields = [
        test_case.get("category", ""),
        test_case.get("scenario", ""),
        test_case.get("preconditions", ""),
        test_case.get("remarks", ""),
    ]
    for step in test_case.get("steps", []) or []:
        if isinstance(step, dict):
            fields.append(step.get("step", ""))
            fields.append(step.get("expected", ""))
    text = "\n".join(str(field).lower() for field in fields)
    return any(keyword in text for keyword in NEGATIVE_KEYWORDS)


def _is_empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _error(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="error", path=path, message=message)


def _warning(path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="warning", path=path, message=message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a draft_test_cases.json file.")
    parser.add_argument("path", help="Path to draft_test_cases.json.")
    parser.add_argument(
        "--report",
        default="",
        help="Optional path to write a JSON validation report.",
    )
    args = parser.parse_args(argv)

    result = validate_draft_file(args.path)
    report = result.as_dict()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
