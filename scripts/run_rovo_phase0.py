"""CLI for the isolated Rovo/Confluence Phase 0 capability spike."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from doc_reader.confluence_phase0 import (  # noqa: E402
    Phase0ConfigurationError,
    auth_config_from_env,
    build_pending_evidence,
    ensure_no_running_event_loop,
    load_attestation,
    load_manifest,
    REQUIRED_ADMIN_CHECKS,
    REQUIRED_FAILURE_OBSERVATIONS,
    rest_config_from_env,
    run_phase0,
    write_evidence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the read-only Rovo MCP Phase 0 hard-gate spike.")
    parser.add_argument("--manifest", type=Path, required=True, help="Fixture-page manifest JSON.")
    parser.add_argument(
        "--auth-mode",
        action="append",
        choices=("personal", "service_account"),
        dest="auth_modes",
        help="Auth mode to verify; repeat for both. Defaults to both.",
    )
    parser.add_argument("--include-rest", action="store_true", help="Also inspect REST v2 storage format.")
    parser.add_argument("--preflight-only", action="store_true", help="Validate config/manifest without network calls.")
    parser.add_argument("--admin-attestation", type=Path, help="Completed admin checklist JSON.")
    parser.add_argument("--failure-observations", type=Path, help="Completed failure-matrix JSON.")
    parser.add_argument("--evidence", type=Path, required=True, help="Sanitized JSON evidence output path.")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--max-total-bytes", type=int, default=8 * 1024 * 1024)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    modes = tuple(args.auth_modes or ("personal", "service_account"))
    manifest = load_manifest(args.manifest)
    admin_attestation = load_attestation(args.admin_attestation, REQUIRED_ADMIN_CHECKS, "admin attestation")
    failure_observations = load_attestation(
        args.failure_observations, REQUIRED_FAILURE_OBSERVATIONS, "failure observations"
    )
    if args.max_pages < 1 or args.max_total_bytes < 1:
        raise SystemExit("--max-pages and --max-total-bytes must be positive")
    if args.preflight_only:
        pending_reasons: list[str] = ["live MCP calls not requested"]
        for mode in modes:
            try:
                auth_config_from_env(mode)
            except Phase0ConfigurationError as exc:
                pending_reasons.append(f"{mode}: {exc}")
        if args.include_rest:
            try:
                rest_config_from_env()
            except Phase0ConfigurationError as exc:
                pending_reasons.append(f"rest: {exc}")
        evidence = build_pending_evidence(
            manifest, modes, pending_reasons, admin_attestation, failure_observations
        )
        write_evidence(args.evidence, evidence)
        return 2
    ensure_no_running_event_loop()
    evidence = asyncio.run(
        run_phase0(
            manifest,
            modes,
            args.include_rest,
            args.max_pages,
            args.max_total_bytes,
            admin_attestation,
            failure_observations,
        )
    )
    write_evidence(args.evidence, evidence)
    return 0 if evidence["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
