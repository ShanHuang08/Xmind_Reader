"""Run the complete new-vendor pipeline for every discovered vendor source."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from regression.vendor_case_baseline import (
    BASELINE_SCHEMA_VERSION,
    baseline_document,
    build_case_profile,
    compare_case_profile,
)


VENDOR_DOCUMENT_RE = re.compile(
    r"^Vendor_(?P<vendor>.+)\.docx?$",
    re.IGNORECASE,
)


def discover_vendors(source_root: Path) -> list[str]:
    """Discover vendor names recursively from Vendor_<Vendor>.doc/docx files."""
    source_root = Path(source_root)
    if not source_root.is_dir():
        raise RuntimeError(f"Vendor source directory does not exist: {source_root}")

    vendors: dict[str, tuple[str, Path]] = {}
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        match = VENDOR_DOCUMENT_RE.fullmatch(path.name)
        if not match:
            continue

        vendor = match.group("vendor").strip()
        if not vendor or vendor in {".", ".."}:
            raise RuntimeError(f"Invalid vendor document name: {path}")
        key = vendor.casefold()
        if key in vendors:
            previous = vendors[key][1]
            raise RuntimeError(
                f"Duplicate vendor documents for {vendor}: {previous} and {path}"
            )
        vendors[key] = (vendor, path)

    if not vendors:
        raise RuntimeError(
            f"No Vendor_*.doc or Vendor_*.docx found under {source_root}"
        )
    return sorted(
        (vendor for vendor, _ in vendors.values()),
        key=str.casefold,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and validate the complete pipeline for every vendor source."
    )
    parser.add_argument(
        "--force-doc-read",
        action="store_true",
        help="Also run main.py new-vendor <vendor> --force after the wrapper check.",
    )
    parser.add_argument(
        "--source-root",
        default="new_vendor_source",
        help="Vendor source directory relative to the repository root.",
    )
    parser.add_argument(
        "--report-dir",
        default="regression-results",
        help="Generated report directory relative to the repository root.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="Maximum runtime for each command. Default: 1800 seconds.",
    )
    parser.add_argument(
        "--baseline",
        default="tests/regression/vendor_case_count_baseline.json",
        help="Version-controlled case-count baseline relative to the repository root.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Replace the baseline after every vendor passes intrinsic validation.",
    )
    return parser


def run_command(
    command: list[str],
    repo_root: Path,
    timeout_seconds: int,
    phase: str,
) -> dict[str, Any]:
    started_at = datetime.now().astimezone()
    started_epoch = time.time()
    started_timer = time.perf_counter()
    output = ""
    exit_code: int | None = None
    timed_out = False
    launch_error = ""

    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        exit_code = completed.returncode
        output = completed.stdout or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = _timeout_output(exc)
    except OSError as exc:
        launch_error = str(exc)
        output = launch_error

    duration = time.perf_counter() - started_timer
    output_failure = _command_output_failure(output) if exit_code == 0 else ""
    return {
        "phase": phase,
        "command": command,
        "command_display": shlex.join(command),
        "started_at": started_at.isoformat(),
        "started_epoch": started_epoch,
        "duration_seconds": round(duration, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "output_failure": output_failure,
        "output": output,
        "passed": (
            exit_code == 0
            and not timed_out
            and not launch_error
            and not output_failure
        ),
    }


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    output = exc.stdout or ""
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return f"{output}\nCommand timed out after {exc.timeout} seconds.".strip()


def _command_output_failure(output: str) -> str:
    patterns = (
        r"Traceback \(most recent call last\):",
        r"(?mi)^ERROR(?:\s|:).+",
        r"(?i)unhandled (?:exception|error)",
    )
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            lines = [line.strip() for line in output[match.start() :].splitlines() if line.strip()]
            return lines[-1] if lines else match.group(0).strip()
    return ""


def validate_vendor_outputs(
    repo_root: Path,
    vendor: str,
    run_started_epoch: float,
    baseline_profile: dict[str, Any] | None = None,
    update_baseline: bool = False,
) -> dict[str, Any]:
    output_dir = repo_root / "output" / vendor
    paths = {
        "draft": output_dir / "draft_test_cases.json",
        "xmind": output_dir / f"{vendor}_test_cases.xmind",
        "validation_report": output_dir / f"{vendor}_test_cases_validation_report.json",
        "summary": output_dir / f"{vendor}_test_cases_summary.md",
    }
    errors: list[str] = []
    fresh = {name: False for name in paths}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"Missing required {name}: {_relative(path, repo_root)}")
            continue
        if path.stat().st_size <= 0:
            errors.append(f"Required {name} is empty: {_relative(path, repo_root)}")
        fresh[name] = path.stat().st_mtime >= run_started_epoch - 2
        if not fresh[name]:
            errors.append(
                f"Required {name} was not regenerated by this run: "
                f"{_relative(path, repo_root)}"
            )

    draft: dict[str, Any] = {}
    report: dict[str, Any] = {}
    test_cases: list[Any] = []
    coverage: dict[str, Any] = {}
    if paths["draft"].is_file():
        draft = _read_json_object(paths["draft"], "draft", errors)
        if draft:
            actual_vendor = str(draft.get("vendor", ""))
            if actual_vendor.casefold() != vendor.casefold():
                errors.append(
                    f"Draft vendor mismatch: expected {vendor!r}, got {actual_vendor!r}."
                )
            value = draft.get("test_cases")
            if not isinstance(value, list) or not value:
                errors.append("Draft test_cases must be a non-empty list.")
            else:
                test_cases = value
            _validate_draft_contract(repo_root, draft, errors)
            current_profile = build_case_profile(draft)
            coverage = compare_case_profile(
                current_profile,
                current_profile if update_baseline else baseline_profile,
            )
            errors.extend(f"Coverage: {error}" for error in coverage["errors"])

    if paths["xmind"].is_file() and not zipfile.is_zipfile(paths["xmind"]):
        errors.append(f"Generated XMind is not a valid ZIP archive: {paths['xmind']}")

    if paths["validation_report"].is_file():
        report = _read_json_object(paths["validation_report"], "validation report", errors)
        if report:
            if report.get("valid") is not True:
                errors.append("XMind validation report is not valid.")
            report_errors = report.get("errors", [])
            if report_errors:
                errors.append(f"XMind validation report contains errors: {report_errors}")
            draft_count = report.get("draft_case_count")
            parsed_count = report.get("parsed_case_count")
            if draft_count != parsed_count:
                errors.append(
                    f"Validation case count mismatch: draft={draft_count}, parsed={parsed_count}."
                )
            if test_cases and draft_count != len(test_cases):
                errors.append(
                    "Validation report draft_case_count does not match "
                    f"draft test_cases: {draft_count} != {len(test_cases)}."
                )
            if not isinstance(parsed_count, int) or parsed_count <= 0:
                errors.append("Validation report parsed_case_count must be greater than zero.")

    if paths["summary"].is_file() and draft:
        _validate_summary_content(paths["summary"], coverage.get("current", {}), errors)

    return {
        "passed": not errors,
        "errors": errors,
        "case_count": len(test_cases),
        "draft_valid": (
            fresh["draft"]
            and bool(draft)
            and bool(test_cases)
            and not any("draft" in error.lower() for error in errors)
        ),
        "xmind_valid": (
            fresh["xmind"]
            and fresh["validation_report"]
            and zipfile.is_zipfile(paths["xmind"])
            and bool(report)
            and report.get("valid") is True
        ),
        "coverage": coverage,
        "artifact_freshness": fresh,
        "paths": {name: _relative(path, repo_root) for name, path in paths.items()},
    }


def _validate_summary_content(
    path: Path, profile: dict[str, Any], errors: list[str]
) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Could not read summary markdown {path}: {exc}")
        return
    total_match = re.search(r"總共產生\s+(\d+)\s+筆", text)
    if not total_match:
        errors.append("Summary markdown does not contain a total case count.")
    elif int(total_match.group(1)) != int(profile.get("total_cases", 0)):
        errors.append(
            "Summary total case count mismatch: "
            f"summary={total_match.group(1)}, draft={profile.get('total_cases', 0)}."
        )

    table_counts = {
        label: int(count)
        for label, count in re.findall(
            r"^\|\s*(User Behavior|API parameter test)\s*\|\s*(\d+)\s*\|\s*$",
            text,
            flags=re.MULTILINE,
        )
    }
    for label in ("User Behavior", "API parameter test"):
        expected = int(profile.get("sections", {}).get(label, 0))
        if label not in table_counts:
            errors.append(f"Summary markdown is missing the {label} count.")
        elif table_counts[label] != expected:
            errors.append(
                f"Summary {label} count mismatch: summary={table_counts[label]}, "
                f"draft={expected}."
            )


def _read_json_object(path: Path, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Invalid {label} JSON at {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label.capitalize()} root must be a JSON object: {path}")
        return {}
    return value


def _validate_draft_contract(
    repo_root: Path,
    draft: dict[str, Any],
    errors: list[str],
) -> None:
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    try:
        from generator.draft_validator import validate_draft

        result = validate_draft(draft)
    except Exception as exc:  # Validation import/runtime failure is a regression failure.
        errors.append(f"Draft contract validation could not run: {exc}")
        return
    if not result.valid:
        messages = [f"{issue.path}: {issue.message}" for issue in result.errors]
        errors.append(f"Draft contract validation failed: {messages}")


def run_vendor(
    repo_root: Path,
    vendor: str,
    force_doc_read: bool,
    timeout_seconds: int,
    logs_dir: Path,
    baseline_profile: dict[str, Any] | None = None,
    update_baseline: bool = False,
) -> dict[str, Any]:
    print(f"[{vendor}] Running wrapper pipeline...", flush=True)
    commands = [
        run_command(
            [sys.executable, "run_new_vendor.py", vendor],
            repo_root,
            timeout_seconds,
            phase="wrapper",
        )
    ]
    if force_doc_read:
        print(f"[{vendor}] Running forced document read pipeline...", flush=True)
        commands.append(
            run_command(
                [sys.executable, "main.py", "new-vendor", vendor, "--force"],
                repo_root,
                timeout_seconds,
                phase="force_doc_read",
            )
        )

    run_started_epoch = min(command["started_epoch"] for command in commands)
    validation = validate_vendor_outputs(
        repo_root,
        vendor,
        run_started_epoch,
        baseline_profile=baseline_profile,
        update_baseline=update_baseline,
    )
    passed = all(command["passed"] for command in commands) and validation["passed"]
    log_path = logs_dir / f"{_safe_name(vendor)}.log"
    result = {
        "vendor": vendor,
        "commands": [_command_summary(command) for command in commands],
        "duration_seconds": round(
            sum(command["duration_seconds"] for command in commands), 3
        ),
        "validation": validation,
        "log_path": _relative(log_path, repo_root),
        "result": "PASS" if passed else "FAIL",
        "passed": passed,
    }
    result["failure_diagnosis"] = _failure_diagnosis(commands, validation)
    log_path.write_text(_render_vendor_log(result, commands), encoding="utf-8")
    print(f"[{vendor}] {result['result']} ({result['duration_seconds']:.3f}s)", flush=True)
    return result


def run_vendor_safely(
    repo_root: Path,
    vendor: str,
    force_doc_read: bool,
    timeout_seconds: int,
    logs_dir: Path,
    baseline_profile: dict[str, Any] | None = None,
    update_baseline: bool = False,
) -> dict[str, Any]:
    try:
        return run_vendor(
            repo_root,
            vendor,
            force_doc_read,
            timeout_seconds,
            logs_dir,
            baseline_profile,
            update_baseline,
        )
    except Exception as exc:  # Keep the suite running so every vendor is attempted.
        message = f"Unexpected regression runner error: {type(exc).__name__}: {exc}"
        log_path = logs_dir / f"{_safe_name(vendor)}.log"
        log_path.write_text(
            f"Vendor: {vendor}\nResult: FAIL\n\n{message}\n",
            encoding="utf-8",
        )
        print(f"[{vendor}] FAIL ({message})", file=sys.stderr, flush=True)
        return {
            "vendor": vendor,
            "commands": [],
            "duration_seconds": 0.0,
            "validation": {
                "passed": False,
                "errors": [message],
                "case_count": 0,
                "draft_valid": False,
                "xmind_valid": False,
                "coverage": {},
                "artifact_freshness": {},
                "paths": {},
            },
            "failure_diagnosis": {
                "stage": "runner",
                "root_cause": message,
                "last_successful_artifact": "",
            },
            "log_path": _relative(log_path, repo_root),
            "result": "FAIL",
            "passed": False,
        }


def _command_summary(command: dict[str, Any]) -> dict[str, Any]:
    return {
        key: command[key]
        for key in (
            "phase",
            "command",
            "command_display",
            "started_at",
            "duration_seconds",
            "exit_code",
            "timed_out",
            "launch_error",
            "output_failure",
            "passed",
        )
    }


def _failure_diagnosis(
    commands: list[dict[str, Any]], validation: dict[str, Any]
) -> dict[str, str]:
    failed_command = next((command for command in commands if not command["passed"]), None)
    if failed_command:
        root_cause = (
            failed_command.get("launch_error")
            or failed_command.get("output_failure")
            or (
                f"Command timed out after its configured limit."
                if failed_command.get("timed_out")
                else f"Command exited with code {failed_command.get('exit_code')}."
            )
        )
        stage = str(failed_command.get("phase", "process"))
    elif validation.get("errors"):
        root_cause = str(validation["errors"][0])
        stage = "artifact_validation"
    else:
        return {"stage": "", "root_cause": "", "last_successful_artifact": ""}

    freshness = validation.get("artifact_freshness", {})
    paths = validation.get("paths", {})
    last_successful = ""
    for name in ("draft", "xmind", "validation_report", "summary"):
        if freshness.get(name):
            last_successful = str(paths.get(name, name))
    return {
        "stage": stage,
        "root_cause": root_cause,
        "last_successful_artifact": last_successful,
    }


def _render_vendor_log(result: dict[str, Any], commands: list[dict[str, Any]]) -> str:
    lines = [
        f"Vendor: {result['vendor']}",
        f"Result: {result['result']}",
        f"Duration seconds: {result['duration_seconds']}",
        "",
    ]
    for command in commands:
        lines.extend(
            [
                f"=== {command['phase']} ===",
                f"Command: {command['command_display']}",
                f"Started: {command['started_at']}",
                f"Exit code: {command['exit_code']}",
                f"Duration seconds: {command['duration_seconds']}",
                f"Timed out: {command['timed_out']}",
                f"Launch error: {command['launch_error'] or 'None'}",
                f"Output failure: {command['output_failure'] or 'None'}",
                "--- combined output ---",
                command["output"].rstrip(),
                "",
            ]
        )
    lines.extend(
        [
            "=== failure diagnosis ===",
            json.dumps(result["failure_diagnosis"], ensure_ascii=False, indent=2),
            "",
            "=== artifact validation ===",
            json.dumps(result["validation"], ensure_ascii=False, indent=2),
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(
    report_dir: Path,
    repo_root: Path,
    started_at: datetime,
    vendors: list[str],
    results: list[dict[str, Any]],
    discovery_error: str = "",
    baseline_path: Path | None = None,
    baseline_updated: bool = False,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    finished_at = datetime.now().astimezone()
    overall_passed = bool(results) and not discovery_error and all(
        result["passed"] for result in results
    )
    payload = {
        "overall_result": "PASS" if overall_passed else "FAIL",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "repository": str(repo_root),
        "git_commit": _git_value(repo_root, ["rev-parse", "HEAD"]),
        "working_tree_dirty": bool(_git_value(repo_root, ["status", "--porcelain"])),
        "python": platform.python_version(),
        "vendor_discovery_count": len(vendors),
        "vendors": vendors,
        "discovery_error": discovery_error,
        "baseline_path": _relative(baseline_path, repo_root) if baseline_path else "",
        "baseline_updated": baseline_updated,
        "preflight": preflight or {},
        "results": results,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_dir / "summary.md").write_text(
        _render_summary_markdown(payload),
        encoding="utf-8",
    )
    _write_case_count_reports(report_dir, payload)
    return payload


def _write_case_count_reports(report_dir: Path, payload: dict[str, Any]) -> None:
    comparisons = {
        result["vendor"]: result.get("validation", {}).get("coverage", {})
        for result in payload.get("results", [])
    }
    comparison_payload = {
        "overall_result": payload["overall_result"],
        "baseline_path": payload.get("baseline_path", ""),
        "baseline_updated": payload.get("baseline_updated", False),
        "vendors": comparisons,
    }
    (report_dir / "case-count-comparison.json").write_text(
        json.dumps(comparison_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Vendor Case Count Comparison",
        "",
        f"- Baseline: `{comparison_payload['baseline_path'] or 'not configured'}`",
        f"- Baseline updated: {comparison_payload['baseline_updated']}",
        f"- Overall result: **{comparison_payload['overall_result']}**",
        "",
        "| Vendor | Total current/base | API parameter current/base | Endpoint current/base | Missing groups | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for vendor, comparison in comparisons.items():
        current = comparison.get("current", {})
        baseline = comparison.get("baseline") or {}
        current_api = current.get("sections", {}).get("API parameter test", 0)
        baseline_api = baseline.get("sections", {}).get("API parameter test", 0)
        lines.append(
            f"| {vendor} | {current.get('total_cases', 0)}/{baseline.get('total_cases', 0)} | "
            f"{current_api}/{baseline_api} | "
            f"{current.get('endpoint_count', 0)}/{baseline.get('endpoint_count', 0)} | "
            f"{len(comparison.get('missing_endpoint_groups', []))} | "
            f"{'PASS' if comparison.get('passed') else 'FAIL'} |"
        )
    failures = {
        vendor: comparison.get("errors", [])
        for vendor, comparison in comparisons.items()
        if comparison.get("errors")
    }
    if failures:
        lines.extend(["", "## Coverage Failures", ""])
        for vendor, errors in failures.items():
            lines.append(f"### {vendor}")
            lines.extend(f"- {error}" for error in errors)
            lines.append("")
    (report_dir / "case-count-comparison.md").write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )


def _render_summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Vendor Regression Report",
        "",
        f"- Commit/working tree: `{payload['git_commit'] or 'unknown'}`"
        f"{' (dirty)' if payload['working_tree_dirty'] else ''}",
        f"- Started: {payload['started_at']}",
        f"- Finished: {payload['finished_at']}",
        f"- Python version: {payload['python']}",
        f"- Vendor discovery count: {payload['vendor_discovery_count']}",
        f"- Baseline: `{payload.get('baseline_path') or 'not configured'}`",
        f"- Baseline updated: {payload.get('baseline_updated', False)}",
        f"- Overall result: **{payload['overall_result']}**",
        "",
        "## Results",
        "",
        "| Vendor | Command | Exit code | Draft valid | XMind valid | Coverage | Case count | Duration | Log | Result |",
        "|---|---|---:|---|---|---|---:|---:|---|---|",
    ]
    for result in payload["results"]:
        wrapper = result["commands"][0] if result["commands"] else {}
        validation = result["validation"]
        lines.append(
            f"| {result['vendor']} | `{wrapper.get('command_display', '')}` | "
            f"{wrapper.get('exit_code')} | "
            f"{validation.get('draft_valid')} | {validation.get('xmind_valid')} | "
            f"{validation.get('coverage', {}).get('passed')} | "
            f"{validation.get('case_count', 0)} | {result['duration_seconds']:.3f}s | "
            f"`{result['log_path']}` | "
            f"{result['result']} |"
        )

    failures = [result for result in payload["results"] if not result["passed"]]
    if payload["discovery_error"] or failures:
        lines.extend(["", "## Failures", ""])
        if payload["discovery_error"]:
            lines.append(f"- Discovery: {payload['discovery_error']}")
        for result in failures:
            errors = result["validation"].get("errors", [])
            command_failures = [
                command
                for command in result["commands"]
                if not command.get("passed")
            ]
            detail = errors or [
                f"{command['phase']} exit_code={command.get('exit_code')}"
                for command in command_failures
            ]
            lines.append(
                f"- {result['vendor']} [{result.get('failure_diagnosis', {}).get('stage', 'unknown')}]: "
                f"{'; '.join(detail)} "
                f"(log: `{result['log_path']}`)"
            )
    preflight = payload.get("preflight", {})
    if preflight:
        lines.extend(
            [
                "",
                "## Preflight",
                "",
                f"- Free disk bytes: {preflight.get('free_disk_bytes')}",
                f"- Python executable: `{preflight.get('python_executable', '')}`",
                "- Git status:",
                "",
                "```text",
                str(preflight.get("git_status_short_branch", "")),
                "```",
            ]
        )
    return "\n".join(lines) + "\n"


def _git_value(repo_root: Path, arguments: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "vendor"


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be greater than zero")

    repo_root = Path(__file__).resolve().parents[1]
    source_root = _resolve_from_repo(repo_root, args.source_root)
    report_dir = _resolve_from_repo(repo_root, args.report_dir)
    baseline_path = _resolve_from_repo(repo_root, args.baseline)
    logs_dir = report_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now().astimezone()
    baseline = _load_baseline(baseline_path, allow_missing=args.update_baseline)
    preflight = _run_preflight(repo_root)
    if preflight["errors"]:
        payload = write_reports(
            report_dir,
            repo_root,
            started_at,
            vendors=[],
            results=[],
            discovery_error="; ".join(preflight["errors"]),
            baseline_path=baseline_path,
            preflight=preflight,
        )
        print("Preflight failed: " + "; ".join(preflight["errors"]), file=sys.stderr)
        print(f"Report: {report_dir / 'summary.md'}")
        return 1 if payload["overall_result"] == "FAIL" else 0

    try:
        vendors = discover_vendors(source_root)
    except RuntimeError as exc:
        payload = write_reports(
            report_dir,
            repo_root,
            started_at,
            vendors=[],
            results=[],
            discovery_error=str(exc),
            baseline_path=baseline_path,
            preflight=preflight,
        )
        print(f"Vendor discovery failed: {exc}", file=sys.stderr)
        print(f"Report: {report_dir / 'summary.md'}")
        return 1 if payload["overall_result"] == "FAIL" else 0

    print(f"Discovered {len(vendors)} vendor(s): {', '.join(vendors)}", flush=True)
    results = [
        run_vendor_safely(
            repo_root,
            vendor,
            args.force_doc_read,
            args.timeout_seconds,
            logs_dir,
            baseline.get("vendors", {}).get(vendor),
            args.update_baseline,
        )
        for vendor in vendors
    ]
    baseline_updated = False
    if args.update_baseline and all(result["passed"] for result in results):
        profiles = {
            result["vendor"]: result["validation"]["coverage"]["current"]
            for result in results
        }
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(baseline_document(profiles), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        baseline_updated = True
        print(f"Baseline updated: {baseline_path}")
    payload = write_reports(
        report_dir,
        repo_root,
        started_at,
        vendors,
        results,
        baseline_path=baseline_path,
        baseline_updated=baseline_updated,
        preflight=preflight,
    )
    print(f"Overall result: {payload['overall_result']}")
    print(f"Report: {report_dir / 'summary.md'}")
    return 0 if payload["overall_result"] == "PASS" else 1


def _load_baseline(path: Path, allow_missing: bool) -> dict[str, Any]:
    if not path.is_file():
        if allow_missing:
            return {"schema_version": BASELINE_SCHEMA_VERSION, "vendors": {}}
        raise SystemExit(
            f"Regression baseline does not exist: {path}. "
            "Run with --update-baseline after reviewing current generated outputs."
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid regression baseline {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise SystemExit(
            f"Unsupported regression baseline schema in {path}; "
            f"expected {BASELINE_SCHEMA_VERSION}."
        )
    if not isinstance(value.get("vendors"), dict):
        raise SystemExit(f"Regression baseline vendors must be an object: {path}")
    return value


def _run_preflight(repo_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    required_paths = [repo_root / "run_new_vendor.py"]
    for path in required_paths:
        if not path.is_file():
            errors.append(f"Required input does not exist: {_relative(path, repo_root)}")
    behavior_maps = [
        path
        for path in repo_root.rglob("*")
        if path.is_file()
        and path.name.casefold() == "user_behavior_map.xmind"
        and not any(
            part.casefold() in {".git", "output", "__pycache__"}
            for part in path.relative_to(repo_root).parts
        )
    ]
    if len(behavior_maps) != 1:
        errors.append(
            "Expected exactly one user_behavior_map.xmind below the repository root; "
            f"found {len(behavior_maps)}."
        )
    dependency_modules = ("bs4", "lxml", "markdownify", "docx")
    missing_dependencies = [
        module for module in dependency_modules if importlib.util.find_spec(module) is None
    ]
    if missing_dependencies:
        errors.append(
            "Missing Python dependencies: " + ", ".join(missing_dependencies)
        )
    free_bytes = shutil.disk_usage(repo_root).free
    minimum_free_bytes = 100 * 1024 * 1024
    if free_bytes < minimum_free_bytes:
        errors.append(
            f"Insufficient free disk space: {free_bytes} bytes; "
            f"at least {minimum_free_bytes} bytes required."
        )
    return {
        "errors": errors,
        "free_disk_bytes": free_bytes,
        "minimum_free_disk_bytes": minimum_free_bytes,
        "git_status_short_branch": _git_value(repo_root, ["status", "--short", "--branch"]),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "checked_python_dependencies": list(dependency_modules),
        "user_behavior_map": (
            _relative(behavior_maps[0], repo_root) if len(behavior_maps) == 1 else ""
        ),
    }


def _resolve_from_repo(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


if __name__ == "__main__":
    raise SystemExit(main())
