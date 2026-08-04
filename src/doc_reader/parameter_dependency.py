"""Compile explicit request-parameter dependency remarks into a normalized profile."""

from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = "parameter-dependencies/v1"
DEPENDENCY_PREFIX_RE = re.compile(r"(?i)\bDependency\s*[:：]\s*")
WHEN_RE = re.compile(
    r"(?is)^when\s+([A-Za-z_][\w./-]*)\s+"
    r"(present|absent|true|false|in\s*\[[^\]]+\]|=\s*[^=]+?)\s*=>\s*(.+)$"
)
OTHERWISE_RE = re.compile(r"(?is)^otherwise\s*=>\s*(.+)$")
ERROR_RE = re.compile(r"(?i)^error\s*=\s*([A-Za-z][A-Za-z0-9_.-]*)$")
GROUP_RE = re.compile(r"(?i)^group\s*=\s*([A-Za-z][A-Za-z0-9_.-]*)$")
OUTCOME_RE = re.compile(r"(?is)^(Y|N)\s*(?:\(([^)]*)\))?$")
HUMAN_BLOCK_HEADING_RE = re.compile(
    r"(?i)^(required?|optional|omit|forbidden)\s+when\s*:?[ \t]*$"
)
HUMAN_CONDITION_RE = re.compile(
    r"^([A-Za-z_][\w./-]*)\s*=\s*([^=]+?)\s*$"
)


def canonical_parameter_path(value: str) -> str:
    """Return the deterministic dot-path used by the dependency engine."""
    return ".".join(part for part in re.split(r"[/.]", str(value).strip()) if part)


def compile_parameter_dependencies(
    endpoints: list[dict[str, Any]], error_codes: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile all explicit remarks and annotate endpoints in place."""
    profiles: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    documented_errors = {
        str(item.get("code", "")).strip() for item in error_codes if isinstance(item, dict)
    }

    for endpoint in endpoints:
        profile, endpoint_issues = _compile_endpoint(endpoint, documented_errors)
        profiles.append(profile)
        issues.extend(endpoint_issues)
        endpoint.update(
            {
                "parameter_dependency": profile["enabled"],
                "parameter_dependency_source": (
                    "request_parameter_remark" if profile["rules"] else ""
                ),
                "dependency_schema_version": SCHEMA_VERSION,
                "dependency_selectors": profile["selectors"],
                "dependency_affected_parameters": profile["affected_parameters"],
                "parameter_dependencies": profile["rules"],
            }
        )

    enabled = [item["endpoint"] for item in profiles if item["enabled"]]
    disabled = [item["endpoint"] for item in profiles if not item["enabled"]]
    profile = {
        "schema_version": SCHEMA_VERSION,
        "endpoints": profiles,
    }
    report = {
        "schema_version": "parameter-dependency-validation-report/v1",
        "valid": not any(item["severity"] == "error" for item in issues),
        "enabled_endpoints": enabled,
        "disabled_endpoints": disabled,
        "errors": [item for item in issues if item["severity"] == "error"],
        "warnings": [item for item in issues if item["severity"] == "warning"],
    }
    return profile, report


def _compile_endpoint(
    endpoint: dict[str, Any], documented_errors: set[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    endpoint_path = str(endpoint.get("endpoint", "")).strip()
    parameters = [
        item
        for item in endpoint.get("request_parameters", [])
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]
    parameter_names = {canonical_parameter_path(item["name"]) for item in parameters}
    rules: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for parameter in parameters:
        name = canonical_parameter_path(parameter.get("name", ""))
        remark = str(parameter.get("remark", ""))
        required = str(parameter.get("required", "")).strip().upper()
        match = DEPENDENCY_PREFIX_RE.search(remark)
        if not match:
            if required != "Y/N":
                continue
            try:
                parsed_rules = _parse_human_blocks(
                    remark, endpoint_path, name, documented_errors, parameters
                )
                _validate_rules(parsed_rules, parameter_names)
            except ValueError as exc:
                issues.append(
                    _issue(
                        "warning",
                        endpoint_path,
                        name,
                        f"Y/N parameter was not enabled: {exc}",
                    )
                )
                continue
            issues.append(
                _issue(
                    "warning",
                    endpoint_path,
                    name,
                    "Human-readable Required/Optional blocks were compiled; BAD_REQUEST was supplied from the documented vendor error codes.",
                )
            )
        else:
            try:
                parsed_rules = _parse_remark(remark[match.end():], endpoint_path, name)
                _validate_rules(parsed_rules, parameter_names)
            except ValueError as exc:
                issues.append(_issue("error", endpoint_path, name, str(exc)))
                continue

        for index, rule in enumerate(parsed_rules, start=1):
            rule["rule_id"] = f"{_slug(endpoint_path)}.{_slug(name)}.{index}"
            error_code = str(rule.get("error_code", ""))
            if error_code and error_code not in documented_errors:
                issues.append(_issue("warning", endpoint_path, name, f"Dependency error code {error_code!r} is not present in error_codes.json."))
            rule["source_evidence"] = {
                "section": endpoint.get("section", ""),
                "table": "Request Parameters",
                "parameter": str(parameter.get("name", "")),
                "column": "Remark",
                "raw_remark": remark,
            }
            rules.append(rule)

    endpoint_errors = [item for item in issues if item["severity"] == "error"]
    selectors = sorted({rule["when"]["field"] for rule in rules if rule["when"].get("field")})
    affected = sorted({rule["affected_field"] for rule in rules})
    return {
        "endpoint": endpoint_path,
        "enabled": bool(rules) and not endpoint_errors,
        "selectors": selectors if not endpoint_errors else [],
        "affected_parameters": affected if not endpoint_errors else [],
        "rules": rules if not endpoint_errors else [],
        "validation_status": "invalid" if endpoint_errors else ("enabled" if rules else "disabled"),
    }, issues


def _parse_remark(text: str, endpoint: str, affected: str) -> list[dict[str, Any]]:
    clauses = [clause.strip().rstrip(".") for clause in re.split(r"\s*;\s*", text) if clause.strip()]
    error_code = ""
    group = ""
    raw_rules: list[dict[str, Any]] = []
    last_selector = ""
    for clause in clauses:
        error_match = ERROR_RE.match(clause)
        if error_match:
            error_code = error_match.group(1)
            continue
        group_match = GROUP_RE.match(clause)
        if group_match:
            group = group_match.group(1)
            continue
        match = WHEN_RE.match(clause)
        otherwise = OTHERWISE_RE.match(clause)
        if match:
            selector = canonical_parameter_path(match.group(1))
            last_selector = selector
            condition = _condition(selector, match.group(2))
            outcome = match.group(3).strip()
        elif otherwise:
            if not last_selector:
                raise ValueError("otherwise clause has no preceding selector")
            condition = {"field": last_selector, "operator": "otherwise"}
            outcome = otherwise.group(1).strip()
        else:
            raise ValueError(f"Cannot parse dependency clause: {clause!r}")
        state, constraint = _outcome(outcome)
        raw_rules.append(
            {
                "when": condition,
                "affected_field": affected,
                "field_state": state,
                **({"value_constraint": constraint} if constraint else {}),
            }
        )
    if not raw_rules:
        raise ValueError("Dependency remark contains no when/otherwise rule")
    if not error_code:
        raise ValueError("Dependency remark must include error=<ERROR_CODE>")
    for rule in raw_rules:
        rule["error_code"] = error_code
        if group:
            rule["group"] = group
    return raw_rules


def _parse_human_blocks(
    text: str,
    endpoint: str,
    affected: str,
    documented_errors: set[str],
    parameters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Parse deterministic Required/Optional blocks without guessing selectors."""
    if "BAD_REQUEST" not in documented_errors:
        raise ValueError(
            "human-readable dependency blocks require documented BAD_REQUEST"
        )
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines:
        raise ValueError("remark has no structured Required/Optional blocks")
    state = ""
    parsed_conditions: list[tuple[str, str, str]] = []
    for line in lines:
        heading = HUMAN_BLOCK_HEADING_RE.match(line)
        if heading:
            keyword = heading.group(1).lower()
            state = {
                "require": "required",
                "required": "required",
                "optional": "optional",
                "omit": "forbidden",
                "forbidden": "forbidden",
            }[keyword]
            continue
        if not state:
            raise ValueError(f"condition appears before a Required/Optional heading: {line!r}")
        condition = HUMAN_CONDITION_RE.match(line)
        if condition:
            selector = canonical_parameter_path(condition.group(1))
            value = condition.group(2).strip().strip("'\"").rstrip(".")
        else:
            selector = ""
            value = line.strip().strip("'\"").rstrip(".")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", value):
                raise ValueError(
                    f"condition must be selector = value or an enum token: {line!r}"
                )
        if not value:
            raise ValueError(f"condition is missing a value: {line!r}")
        parsed_conditions.append((state, selector, value))

    explicit_selectors = {selector for _, selector, _ in parsed_conditions if selector}
    bare_values = [value for _, selector, value in parsed_conditions if not selector]
    inferred_selector = ""
    if bare_values:
        if len(explicit_selectors) == 1:
            inferred_selector = next(iter(explicit_selectors))
        elif explicit_selectors:
            raise ValueError(
                "value-only conditions cannot inherit more than one explicit selector"
            )
        else:
            inferred_selector = _unique_enum_selector(
                bare_values, affected, parameters
            )

    rules: list[dict[str, Any]] = []
    for field_state, selector, value in parsed_conditions:
        resolved_selector = selector or inferred_selector
        rules.append(
            {
                "when": {
                    "field": resolved_selector,
                    "operator": "eq",
                    "value": value,
                },
                "affected_field": affected,
                "field_state": field_state,
                "error_code": "BAD_REQUEST",
                "error_code_source": "documented_vendor_error_default",
                "source_grammar": "human-required-optional-blocks/v1",
                "selector_source": (
                    "explicit_condition" if selector else "unique_enum_value_owner"
                ),
            }
        )
    states = {rule["field_state"] for rule in rules}
    if "required" not in states or not states.intersection({"optional", "forbidden"}):
        raise ValueError(
            "structured dependency must contain Required and Optional/Omit blocks"
        )
    return rules


def _unique_enum_selector(
    values: list[str],
    affected: str,
    parameters: list[dict[str, Any]],
) -> str:
    candidates: list[str] = []
    for parameter in parameters:
        name = canonical_parameter_path(parameter.get("name", ""))
        if not name or name == affected:
            continue
        evidence = _documented_enum_evidence(parameter)
        if not evidence:
            continue
        if all(
            re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", evidence)
            for value in values
        ):
            candidates.append(name)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            "value-only conditions do not uniquely match any parameter's documented allowed values"
        )
    raise ValueError(
        "value-only conditions match multiple possible selectors: "
        + ", ".join(sorted(candidates))
    )


def _documented_enum_evidence(parameter: dict[str, Any]) -> str:
    """Use enum declarations, never dependency prose, as selector ownership evidence."""
    evidence: list[str] = []
    explicit_values = parameter.get("allowed_values")
    if isinstance(explicit_values, list):
        evidence.extend(str(value) for value in explicit_values)
    elif explicit_values:
        evidence.append(str(explicit_values))
    for key in ("description", "remark"):
        text = str(parameter.get(key, ""))
        normalized = text.lower()
        if any(
            marker in normalized
            for marker in ("allowed values", "following values", "one of")
        ):
            evidence.append(text)
    return "\n".join(evidence)


def _condition(field: str, expression: str) -> dict[str, Any]:
    value = expression.strip()
    lowered = value.lower()
    if lowered in {"present", "absent", "true", "false"}:
        return {"field": field, "operator": lowered}
    if lowered.startswith("in"):
        content = value[value.find("[") + 1:value.rfind("]")]
        values = [item.strip().strip("'\"") for item in content.split(",") if item.strip()]
        if not values:
            raise ValueError("in [...] condition must contain at least one value")
        return {"field": field, "operator": "in", "values": values}
    if value.startswith("="):
        scalar = value[1:].strip().strip("'\"")
        if not scalar:
            raise ValueError("equals condition is missing a value")
        return {"field": field, "operator": "eq", "value": scalar}
    raise ValueError(f"Unsupported dependency condition: {expression!r}")


def _outcome(value: str) -> tuple[str, dict[str, Any] | None]:
    match = OUTCOME_RE.match(value)
    if not match:
        raise ValueError(f"Invalid dependency outcome: {value!r}")
    required = match.group(1).upper() == "Y"
    qualifier = (match.group(2) or "").strip()
    if not required:
        lowered = qualifier.lower()
        if lowered == "optional":
            return "optional", None
        if lowered in {"omit", "forbidden"}:
            return "forbidden", None
        raise ValueError("N outcome must specify N(optional) or N(omit)")
    if not qualifier:
        return "required", None
    constraint = _value_constraint(qualifier)
    return "required", constraint


def _value_constraint(value: str) -> dict[str, Any]:
    match = re.fullmatch(r"(?i)value\s*(=|>|>=|<|<=)\s*(.+)", value.strip())
    if not match:
        raise ValueError(f"Unsupported Y(...) qualifier: {value!r}")
    return {"operator": match.group(1), "value": _scalar(match.group(2).strip())}


def _scalar(value: str) -> Any:
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value.strip("'\"")


def _validate_rules(rules: list[dict[str, Any]], parameter_names: set[str]) -> None:
    for rule in rules:
        selector = rule["when"].get("field", "")
        affected = rule["affected_field"]
        if selector not in parameter_names:
            raise ValueError(f"Selector {selector!r} does not exist in the endpoint request parameters")
        if affected not in parameter_names:
            raise ValueError(f"Affected field {affected!r} does not exist in the endpoint request parameters")


def _issue(severity: str, endpoint: str, parameter: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "endpoint": endpoint, "parameter": parameter, "message": message}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "rule"
