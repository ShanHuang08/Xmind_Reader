"""CLI for generating draft test cases and writing the final XMind file."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from generator.case_generation_context import load_draft
from generator.draft_builder import build_draft
from generator.test_case_generator import generate_test_cases_file
from xmind_writer.metersphere_xmind_writer import write_xmind_from_draft
from xmind_writer.xmind_validator import validate_generated_xmind


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a draft, generate structured test cases, and write the final XMind file."
    )
    parser.add_argument("--vendor", required=True, help="Vendor folder name.")
    parser.add_argument(
        "--vendor-detail",
        default="new_vendor_detail",
        help="Folder containing parsed vendor details. Default: new_vendor_detail",
    )
    parser.add_argument("--output", default="output", help="Output root folder. Default: output")
    parser.add_argument(
        "--xmind-detail",
        default="xmind_detail",
        help="Reference XMind detail root. Default: xmind_detail",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    draft_path = build_draft(args.vendor, Path(args.vendor_detail), Path(args.output))
    LOGGER.info("[%s] Draft JSON written to %s", args.vendor, draft_path)

    generate_test_cases_file(
        draft_path,
        xmind_detail_root=args.xmind_detail,
        replace_generated=True,
    )
    after = load_draft(draft_path)
    after_count = len(after.get("test_cases", [])) if isinstance(after.get("test_cases"), list) else 0
    LOGGER.info("[%s] Generated draft cases: %s", args.vendor, after_count)

    xmind_path = Path(args.output) / args.vendor / f"{args.vendor}_test_cases.xmind"
    report_path = xmind_path.with_name(f"{xmind_path.stem}_validation_report.json")
    write_xmind_from_draft(after, xmind_path)
    report = validate_generated_xmind(xmind_path, after, report_path)
    LOGGER.info("[%s] XMind written to %s", args.vendor, xmind_path)
    LOGGER.info("[%s] Validation report written to %s", args.vendor, report_path)
    if not report.get("valid"):
        LOGGER.error(
            "[%s] XMind validation failed: %s",
            args.vendor,
            json.dumps(report.get("errors", []), ensure_ascii=False),
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
