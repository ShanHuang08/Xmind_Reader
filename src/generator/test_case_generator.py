"""Generate structured draft test cases from parsed vendor details."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from generator.case_generation_context import build_generation_context, load_draft, save_draft
from generator.draft_schema import (
    API_PARAMETER_CASE_TITLE_TEMPLATE,
    API_PARAMETER_TEST_SECTION,
    PRECONDITIONS_LABEL,
    REMARKS_LABEL,
)
from generator.draft_validator import validate_draft
from generator.reference_selector import selected_categories, select_reference_files


GENERATED_BY = "deterministic-parameter-generator/v1"


def generate_test_cases_for_draft(
    draft: dict[str, Any],
    xmind_detail_root: Path | str = "xmind_detail",
    include_parameter_validation: bool = True,
) -> list[dict[str, Any]]:
    """Generate cases from a draft object.

    The first implementation covers API parameter validation because those cases
    are fully derivable from endpoint request parameter tables.
    """
    context = build_generation_context(draft)
    categories = selected_categories(context.get("capability_profile", {}))
    references = [str(path) for path in select_reference_files(xmind_detail_root, categories)]
    cases: list[dict[str, Any]] = []

    if include_parameter_validation:
        cases.extend(_parameter_validation_cases(context, references))

    return cases


def generate_test_cases_file(
    draft_path: Path | str,
    xmind_detail_root: Path | str = "xmind_detail",
    replace_generated: bool = True,
) -> Path:
    """Generate cases and write them back into draft_test_cases.json."""
    path = Path(draft_path)
    draft = load_draft(path)
    generated_cases = generate_test_cases_for_draft(draft, xmind_detail_root=xmind_detail_root)

    existing_cases = draft.get("test_cases", [])
    if not isinstance(existing_cases, list):
        existing_cases = []

    if replace_generated:
        existing_cases = [
            case
            for case in existing_cases
            if not (
                isinstance(case, dict)
                and case.get("source_reference", {}).get("generated_by") == GENERATED_BY
            )
        ]

    draft["status"] = "generated_test_cases"
    draft["test_cases"] = existing_cases + generated_cases
    result = validate_draft(draft)
    if not result.valid:
        messages = "; ".join(f"{issue.path}: {issue.message}" for issue in result.errors)
        raise ValueError(f"Generated draft failed validation: {messages}")

    return save_draft(draft, path)


def _parameter_validation_cases(
    context: dict[str, Any], reference_files: list[str]
) -> list[dict[str, Any]]:
    cases = []
    for endpoint in context.get("endpoint_roles", []):
        endpoint_name = endpoint.get("endpoint", "")
        if not endpoint_name:
            continue
        for parameter in endpoint.get("request_parameters", []):
            parameter_name = parameter.get("name", "")
            if not parameter_name:
                continue
            cases.append(_parameter_case(context, endpoint, parameter, reference_files))
    return cases


def _parameter_case(
    context: dict[str, Any],
    endpoint: dict[str, Any],
    parameter: dict[str, Any],
    reference_files: list[str],
) -> dict[str, Any]:
    endpoint_name = endpoint.get("endpoint", "")
    endpoint_display_name = _endpoint_display_name(endpoint_name)
    parameter_name = parameter.get("name", "")
    scenario = API_PARAMETER_CASE_TITLE_TEMPLATE.format(parameter=parameter_name)
    expected_error = deepcopy(context.get("parameter_error", {}))
    if expected_error.get("source", "").startswith("inferred") and "inference_reason" not in expected_error:
        expected_error["inference_reason"] = (
            "No endpoint-specific parameter validation code was found; selected the closest documented vendor code."
        )

    return {
        "output_section": API_PARAMETER_TEST_SECTION,
        "module": endpoint_display_name,
        "category": "parameter_validation",
        "scenario": scenario,
        "endpoint": endpoint_name,
        "endpoint_name": endpoint_display_name,
        "endpoint_group": endpoint.get("role", ""),
        "endpoints": [endpoint_name],
        "parameter": parameter_name,
        "preconditions": _preconditions(context, endpoint, parameter),
        "steps": _parameter_steps(endpoint, parameter, expected_error),
        "remarks": _remarks(endpoint),
        "expected_error": expected_error,
        "tags": ["parameter_validation", "negative"],
        "priority": "P2",
        "source_reference": {
            "generated_by": GENERATED_BY,
            "vendor_doc": [endpoint_name],
            "xmind_reference_cases": reference_files,
        },
        "unresolved_questions": [],
    }


def _preconditions(
    context: dict[str, Any], endpoint: dict[str, Any], parameter: dict[str, Any]
) -> str:
    endpoint_name = endpoint.get("endpoint", "")
    game_code = context.get("case_authoring_rules", {}).get("default_game_code") or "<confirm gameCode>"
    request = _request_payload(endpoint, parameter.get("name", ""))
    return (
        f"{PRECONDITIONS_LABEL}\n"
        f"1. launch game {game_code}\n"
        f"2. url：{endpoint_name}\n"
        f"3. 测试账号：{context.get('default_test_account', '')}\n\n"
        "API request parameters：\n"
        "<code>\n"
        f"{request}\n"
        "</code>"
    )


def _remarks(endpoint: dict[str, Any]) -> str:
    response = _response_payload(endpoint)
    return (
        f"{REMARKS_LABEL}\n"
        "Success response：\n"
        "<code>\n"
        f"{response}\n"
        "</code>"
    )


def _parameter_steps(
    endpoint: dict[str, Any], parameter: dict[str, Any], expected_error: dict[str, Any]
) -> list[dict[str, str]]:
    parameter_name = str(parameter.get("name", "parameter"))
    lowered = parameter_name.lower()
    code = expected_error.get("code", "UNKNOWN_PARAMETER_ERROR")
    error_response = _json_block(_expected_error_response(endpoint, expected_error))
    steps: list[dict[str, str]] = []

    if "amount" in lowered:
        amount_cases = [
            ("amount doesn't set", '// "amount": 100.0'),
            ("amount Input blank", '"amount": ""'),
            (
                "amount Input exceed 20 digit numbers",
                '"amount": 123456789012345678901',
            ),
            ("amount Input 9 decimal numbers", '"amount": 100.123456789'),
            ("amount Input negative number", '"amount": -100.0'),
            ("amount Input space", '"amount": " 100.0 "'),
            ("amount Input string", '"amount": "test"'),
        ]
        return [
            _step_case(title, request_line, code, error_response)
            for title, request_line in amount_cases
        ]

    steps.append(
        _step_case(
            f"{parameter_name} doesn't set",
            f'// "{parameter_name}": {_normal_request_value(endpoint, parameter)}',
            code,
            error_response,
        )
    )
    steps.append(
        _step_case(
            f"{parameter_name} leave blank",
            f'"{parameter_name}": ""',
            code,
            error_response,
        )
    )

    if lowered == "gamename":
        steps.append(
            _step_case("input wrong gameName", '"gameName": "wrongGameName"', code, error_response)
        )
    elif lowered == "hash":
        steps.append(
            _step_case("hash input wrong value", '"hash": "wrongvalue"', code, error_response)
        )
    elif lowered == "rounddetails":
        steps.append(
            _step_case("roundDetails input int", '"roundDetails": 123', code, error_response)
        )
    else:
        steps.append(
            _step_case(
                f"{parameter_name} input wrong value",
                _wrong_value_request_line(parameter),
                code,
                error_response,
            )
        )

    if lowered == "userid":
        steps.append(
            _step_case("userId input space", '"userId": " playerA "', code, error_response)
        )
    if lowered == "roundid":
        steps.append(
            _step_case("roundId input space", '"roundId": " 123 "', code, error_response)
        )
    if lowered == "timestamp":
        steps.append(
            _step_case(
                "timestamp Input shorter timestamp",
                '"timestamp": 1722345',
                code,
                error_response,
            )
        )

    return steps


def _step_case(
    title: str, request_line: str, expected_code: str, error_response: str
) -> dict[str, str]:
    return {
        "step": f"{title}\n{request_line}",
        "expected": (
            f"The API returns a parameter validation error with error code {expected_code}.\n"
            f"{error_response}"
        ),
    }


def _normal_request_value(endpoint: dict[str, Any], parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", ""))
    example = endpoint.get("request_example")
    if isinstance(example, dict) and name in example:
        return json.dumps(example[name], ensure_ascii=False)
    return _sample_value(parameter)


def _expected_error_response(
    endpoint: dict[str, Any], expected_error: dict[str, Any]
) -> dict[str, Any]:
    error = endpoint.get("error_response_example")
    code = expected_error.get("code", "ERROR")
    message = expected_error.get("description") or "Parameter validation error"
    if isinstance(error, dict) and error:
        patched = deepcopy(error)
        patched.setdefault("error", {})
        if isinstance(patched["error"], dict):
            patched["error"]["code"] = code
            patched["error"]["message"] = message
        return patched
    return {
        "result": "ERROR",
        "timestamp": "20110322T152403Z",
        "error": {
            "code": code,
            "message": message,
        },
    }


def _wrong_value_request_line(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "parameter"))
    param_type = str(parameter.get("type", "")).lower()
    if "int" in param_type or "long" in param_type or "decimal" in param_type:
        return f'"{name}": "test"'
    if "bool" in param_type:
        return f'"{name}": "test"'
    return f'"{name}": 123'


def _endpoint_display_name(endpoint_path: str) -> str:
    text = str(endpoint_path or "").strip().rstrip("/")
    if not text:
        return "unknown"
    return text.rsplit("/", 1)[-1] or text


def _sample_request(parameters: list[dict[str, Any]], focus_parameter: str) -> str:
    lines = ["{"]
    for index, parameter in enumerate(parameters):
        name = parameter.get("name", f"parameter{index + 1}")
        sample = _sample_value(parameter)
        suffix = "," if index < len(parameters) - 1 else ""
        marker = "  // focus" if name == focus_parameter else ""
        lines.append(f'  "{name}": {sample}{suffix}{marker}')
    lines.append("}")
    return "\n".join(lines)


def _request_payload(endpoint: dict[str, Any], focus_parameter: str) -> str:
    example = endpoint.get("request_example")
    if isinstance(example, dict) and example:
        return _json_block(example, focus_parameter=focus_parameter)
    return _sample_request(endpoint.get("request_parameters", []), focus_parameter)


def _response_payload(endpoint: dict[str, Any]) -> str:
    success = endpoint.get("success_response_example")
    error = endpoint.get("error_response_example")
    parts = []
    if isinstance(success, dict) and success:
        parts.append(_json_block(success))
    else:
        parts.append(_sample_response(endpoint.get("response_parameters", [])))
    if isinstance(error, dict) and error:
        parts.append("// Error response")
        parts.append(_json_block(error))
    return "\n".join(parts)


def _json_block(data: dict[str, Any], focus_parameter: str = "") -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if not focus_parameter:
        return text
    lines = []
    needle = f'"{focus_parameter}":'
    for line in text.splitlines():
        if needle in line:
            line += "  // focus"
        lines.append(line)
    return "\n".join(lines)


def _sample_response(parameters: list[dict[str, Any]]) -> str:
    lines = ["{"]
    for index, parameter in enumerate(parameters):
        name = parameter.get("name", f"field{index + 1}")
        sample = _sample_value(parameter)
        suffix = "," if index < len(parameters) - 1 else ""
        lines.append(f'  "{name}": {sample}{suffix}')
    lines.append("}")
    return "\n".join(lines)


def _sample_value(parameter: dict[str, Any]) -> str:
    name = str(parameter.get("name", "")).lower()
    param_type = str(parameter.get("type", "")).lower()
    description = str(parameter.get("description", "")).lower()
    text = " ".join([name, param_type, description])

    if "amount" in text:
        return "100.0"
    if "balance" in text or "cash" in text or "bonus" in text:
        return "100"
    if "url" in name or "url" in description:
        return '"https://example.com/replay/4330252729"'
    if "numeric string" in param_type:
        return '"10"'
    if name.endswith("id") or " identifier" in description or " id" in description:
        return f'"{parameter.get("name", "id")}_001"'
    if "timestamp" in text or "time" in text:
        return "1786335355774"
    if "int" in param_type or "long" in param_type or "decimal" in param_type:
        return "1"
    if "bool" in param_type:
        return "true"
    return f'"sample_{parameter.get("name", "value")}"'
