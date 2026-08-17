"""Build and compare deterministic vendor test-case coverage profiles."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any


BASELINE_SCHEMA_VERSION = "vendor-case-count-baseline/v1"
TOTAL_CASE_DECREASE_LIMIT = 0.10
API_PARAMETER_DECREASE_LIMIT = 0.05
API_PARAMETER_SECTION = "API parameter test"
USER_BEHAVIOR_GENERATOR = "user-behavior-reference-generator/v1"


def build_case_profile(draft: dict[str, Any]) -> dict[str, Any]:
    cases = [case for case in draft.get("test_cases", []) if isinstance(case, dict)]
    section_counts = Counter(str(case.get("output_section", "")) for case in cases)
    category_counts = Counter(str(case.get("category", "")) for case in cases)
    api_cases = [case for case in cases if case.get("output_section") == API_PARAMETER_SECTION]
    user_behavior_cases = [
        case
        for case in cases
        if (case.get("source_reference") or {}).get("generated_by")
        == USER_BEHAVIOR_GENERATOR
    ]
    generated_by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in api_cases:
        generated_by_group[
            endpoint_group_key(case.get("endpoint", ""), case.get("endpoint_operation", ""))
        ].append(case)

    skips = _coverage_skips(draft)
    endpoint_profiles: dict[str, dict[str, Any]] = {}
    for endpoint in _parameter_endpoint_specs(draft):
        key = endpoint_group_key(endpoint["endpoint"], endpoint["operation"])
        expected_parameters = _expected_parameter_names(endpoint)
        generated_cases = generated_by_group.get(key, [])
        generated_parameters = sorted(
            {
                str(case.get("parameter", "")).strip()
                for case in generated_cases
                if str(case.get("parameter", "")).strip()
            },
            key=str.casefold,
        )
        skipped = skips.get(key, {})
        missing = [
            name
            for name in expected_parameters
            if not _parameter_is_covered(name, generated_parameters)
            and name not in skipped
        ]
        endpoint_profiles[key] = {
            "endpoint": endpoint["endpoint"],
            "operation": endpoint["operation"],
            "request_parameter_count": len(expected_parameters),
            "request_parameters": expected_parameters,
            "generated_parameter_case_count": len(generated_cases),
            "generated_parameter_count": len(generated_parameters),
            "generated_parameters": generated_parameters,
            "missing_parameters": missing,
            "skipped_parameters": [
                {"parameter": name, "skip_reason": skipped[name]}
                for name in sorted(skipped, key=str.casefold)
            ],
            "has_request_example": bool(endpoint.get("request_example")),
            "has_success_response_example": bool(endpoint.get("success_response_example")),
            "has_error_response_example": bool(endpoint.get("error_response_example")),
        }

    endpoint_roles = [
        endpoint for endpoint in draft.get("endpoint_roles", []) if isinstance(endpoint, dict)
    ]
    return {
        "total_cases": len(cases),
        "sections": {
            "API parameter test": len(api_cases),
            "User Behavior": len(user_behavior_cases),
            "Other cases": len(cases) - len(api_cases) - len(user_behavior_cases),
        },
        "section_counts": dict(sorted(section_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "endpoint_count": len(endpoint_roles),
        "parameter_endpoint_count": len(endpoint_profiles),
        "operation_variant_count": sum(
            1 for profile in endpoint_profiles.values() if profile["operation"]
        ),
        "endpoints": dict(sorted(endpoint_profiles.items())),
        "semantic_checks": {
            "amount_precision_cases": category_counts.get("amount_precision", 0),
            "dependency_parameter_cases": category_counts.get(
                "parameter_dependency_validation", 0
            ),
            "encryption_errors": _encryption_error_map(api_cases),
        },
    }


def compare_case_profile(
    current: dict[str, Any], baseline: dict[str, Any] | None
) -> dict[str, Any]:
    errors = intrinsic_coverage_errors(current)
    warnings: list[str] = []
    if baseline is None:
        errors.append(
            "No case-count baseline exists for this vendor. Run with --update-baseline "
            "after reviewing the generated XMind."
        )
    else:
        errors.extend(_baseline_errors(current, baseline))

    current_keys = set(current.get("endpoints", {}))
    baseline_keys = set((baseline or {}).get("endpoints", {}))
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "current": current,
        "baseline": deepcopy(baseline) if baseline is not None else None,
        "missing_endpoint_groups": sorted(baseline_keys - current_keys),
        "new_endpoint_groups": sorted(current_keys - baseline_keys),
    }


def intrinsic_coverage_errors(profile: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key, endpoint in profile.get("endpoints", {}).items():
        expected_count = int(endpoint.get("request_parameter_count", 0))
        generated_count = int(endpoint.get("generated_parameter_case_count", 0))
        if expected_count > 0 and generated_count == 0:
            errors.append(f"Endpoint group {key!r} has request parameters but generated 0 cases.")
        missing = endpoint.get("missing_parameters", [])
        if missing:
            errors.append(
                f"Endpoint group {key!r} is missing generated parameter coverage: "
                f"{', '.join(str(value) for value in missing)}."
            )
    return errors


def baseline_document(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "vendors": {
            vendor: _baseline_profile(profile)
            for vendor, profile in sorted(profiles.items(), key=lambda item: item[0].casefold())
        },
    }


def _baseline_profile(profile: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(profile)
    for endpoint in value.get("endpoints", {}).values():
        endpoint.pop("missing_parameters", None)
    return value


def _baseline_errors(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _append_decrease_error(
        errors,
        "Total test case count",
        int(current.get("total_cases", 0)),
        int(baseline.get("total_cases", 0)),
        TOTAL_CASE_DECREASE_LIMIT,
    )
    _append_decrease_error(
        errors,
        "API parameter test count",
        int(current.get("sections", {}).get(API_PARAMETER_SECTION, 0)),
        int(baseline.get("sections", {}).get(API_PARAMETER_SECTION, 0)),
        API_PARAMETER_DECREASE_LIMIT,
    )
    if int(current.get("endpoint_count", 0)) < int(baseline.get("endpoint_count", 0)):
        errors.append(
            "Parsed endpoint count decreased: "
            f"baseline={baseline.get('endpoint_count', 0)}, current={current.get('endpoint_count', 0)}."
        )

    current_endpoints = current.get("endpoints", {})
    baseline_endpoints = baseline.get("endpoints", {})
    for key in sorted(set(baseline_endpoints) - set(current_endpoints)):
        errors.append(f"Baseline endpoint/operation coverage disappeared: {key}.")
    for key in sorted(set(baseline_endpoints) & set(current_endpoints)):
        before = baseline_endpoints[key]
        after = current_endpoints[key]
        if int(after.get("request_parameter_count", 0)) < int(
            before.get("request_parameter_count", 0)
        ):
            errors.append(
                f"Request parameter count decreased for {key}: "
                f"baseline={before.get('request_parameter_count', 0)}, "
                f"current={after.get('request_parameter_count', 0)}."
            )
        missing_generated = set(before.get("generated_parameters", [])) - set(
            after.get("generated_parameters", [])
        )
        if missing_generated:
            errors.append(
                f"Generated parameter coverage disappeared for {key}: "
                f"{', '.join(sorted(missing_generated, key=str.casefold))}."
            )
        for field in (
            "has_request_example",
            "has_success_response_example",
            "has_error_response_example",
        ):
            if before.get(field) is True and after.get(field) is not True:
                errors.append(f"Documented {field} disappeared for {key}.")

    current_categories = current.get("category_counts", {})
    for category, count in baseline.get("category_counts", {}).items():
        if int(count) > 0 and int(current_categories.get(category, 0)) == 0:
            errors.append(f"Generated category disappeared: {category}.")

    before_semantics = baseline.get("semantic_checks", {})
    after_semantics = current.get("semantic_checks", {})
    for field in ("amount_precision_cases", "dependency_parameter_cases"):
        if int(after_semantics.get(field, 0)) < int(before_semantics.get(field, 0)):
            errors.append(
                f"Semantic case count decreased for {field}: "
                f"baseline={before_semantics.get(field, 0)}, "
                f"current={after_semantics.get(field, 0)}."
            )
    for key, code in before_semantics.get("encryption_errors", {}).items():
        current_code = after_semantics.get("encryption_errors", {}).get(key)
        if current_code != code:
            errors.append(
                f"Encryption error mapping changed for {key}: "
                f"baseline={code!r}, current={current_code!r}."
            )
    return errors


def _append_decrease_error(
    errors: list[str], label: str, current: int, baseline: int, limit: float
) -> None:
    if baseline <= 0:
        return
    decrease = (baseline - current) / baseline
    if decrease > limit:
        errors.append(
            f"{label} decreased by {decrease:.1%}: baseline={baseline}, "
            f"current={current}, allowed={limit:.0%}."
        )


def _parameter_endpoint_specs(draft: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for endpoint in draft.get("endpoint_roles", []):
        if not isinstance(endpoint, dict):
            continue
        variants = [
            variant
            for variant in endpoint.get("operation_variants", [])
            if isinstance(variant, dict) and variant.get("request_parameters")
        ]
        if variants:
            for variant in variants:
                output.append(_endpoint_spec(endpoint, variant))
        else:
            output.append(_endpoint_spec(endpoint, None))
    return output


def _endpoint_spec(
    endpoint: dict[str, Any], variant: dict[str, Any] | None
) -> dict[str, Any]:
    source = variant or endpoint
    return {
        "endpoint": str(endpoint.get("endpoint", "")).strip(),
        "operation": str(source.get("operation", "")).strip() if variant else "",
        "request_parameters": source.get("request_parameters", []),
        "request_example": source.get("request_example", endpoint.get("request_example", {})),
        "success_response_example": source.get(
            "success_response_example", endpoint.get("success_response_example", {})
        ),
        "error_response_example": source.get(
            "error_response_example", endpoint.get("error_response_example", {})
        ),
    }


def _expected_parameter_names(endpoint: dict[str, Any]) -> list[str]:
    names = [
        match.group(1).strip()
        for match in re.finditer(r"\{([^{}]+)\}", endpoint.get("endpoint", ""))
        if match.group(1).strip()
    ]
    names.extend(
        str(parameter.get("name", "")).strip()
        for parameter in endpoint.get("request_parameters", [])
        if isinstance(parameter, dict) and str(parameter.get("name", "")).strip()
    )
    return sorted(set(names), key=str.casefold)


def _coverage_skips(draft: dict[str, Any]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = defaultdict(dict)
    for item in draft.get("parameter_coverage_skips", []):
        if not isinstance(item, dict):
            continue
        endpoint = str(item.get("endpoint", "")).strip()
        parameter = str(item.get("parameter", "")).strip()
        reason = str(item.get("skip_reason", "")).strip()
        if endpoint and parameter and reason:
            output[endpoint_group_key(endpoint, item.get("operation", ""))][parameter] = reason
    return output


def _parameter_is_covered(expected: str, generated: list[str]) -> bool:
    expected_path = expected.replace(".", "/").strip("/")
    for value in generated:
        generated_path = value.replace(".", "/").strip("/")
        if generated_path == expected_path:
            return True
        if "/" not in expected_path and generated_path.endswith(f"/{expected_path}"):
            return True
    return False


def _encryption_error_map(api_cases: list[dict[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for case in api_cases:
        parameter = str(case.get("parameter", ""))
        if not set(re.findall(r"[a-z]+", parameter.lower())) & {
            "hmac",
            "signature",
            "sign",
            "hash",
            "encrypt",
            "decrypt",
        }:
            continue
        code = str((case.get("expected_error") or {}).get("code", "")).strip()
        key = f"{endpoint_group_key(case.get('endpoint', ''), case.get('endpoint_operation', ''))}::{parameter}"
        output[key] = code
    return dict(sorted(output.items()))


def endpoint_group_key(endpoint: Any, operation: Any) -> str:
    endpoint_text = str(endpoint).strip()
    operation_text = str(operation).strip()
    return f"{endpoint_text}::{operation_text}" if operation_text else endpoint_text
