"""CLI for generating draft test cases and writing the final XMind file."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from generator.case_generation_context import load_draft, save_draft
from generator.draft_builder import build_draft
from generator.human_xmind_merger import (
    ensure_stable_case_ids,
    merge_human_xmind_edits,
    write_human_merge_manifest,
)
from generator.test_case_generator import generate_test_cases_file
from generator.test_case_summary import write_test_case_summary
from xmind_writer.metersphere_xmind_writer import write_no_merge_key_copy, write_xmind_from_draft
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
    parser.add_argument(
        "--human-xmind",
        default="",
        help="Optional human-edited XMind copy to merge before writing the final XMind.",
    )
    parser.add_argument(
        "--show-case-id",
        action="store_true",
        help="Deprecated compatibility option. Visible ID topics are always written.",
    )
    parser.add_argument(
        "--no-merge-key-copy",
        action="store_true",
        help="Also export a delivery XMind copy with visible merge_key topics removed.",
    )
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
    ensure_stable_case_ids(after)
    manifest_path = Path(args.output) / args.vendor / f"{args.vendor}_human_merge_manifest.json"
    merge_report_path = Path(args.output) / args.vendor / f"{args.vendor}_human_merge_report.md"
    if args.human_xmind:
        after = merge_human_xmind_edits(
            after,
            Path(args.human_xmind),
            merge_report_path,
            manifest_path,
        )
    save_draft(after, draft_path)
    after_count = len(after.get("test_cases", [])) if isinstance(after.get("test_cases"), list) else 0
    LOGGER.info("[%s] Generated draft cases: %s", args.vendor, after_count)

    xmind_path = Path(args.output) / args.vendor / f"{args.vendor}_test_cases.xmind"
    report_path = xmind_path.with_name(f"{xmind_path.stem}_validation_report.json")
    summary_path = xmind_path.with_name(f"{xmind_path.stem}_summary.md")
    write_xmind_from_draft(after, xmind_path, show_case_id=args.show_case_id)
    report = validate_generated_xmind(xmind_path, after, report_path)
    write_test_case_summary(after, summary_path)
    write_human_merge_manifest(after, manifest_path)
    no_key_path = None
    if args.no_merge_key_copy:
        no_key_path = write_no_merge_key_copy(xmind_path)
    LOGGER.info("[%s] XMind written to %s", args.vendor, xmind_path)
    LOGGER.info("[%s] Validation report written to %s", args.vendor, report_path)
    LOGGER.info("[%s] Summary markdown written to %s", args.vendor, summary_path)
    LOGGER.info("[%s] Human merge manifest written to %s", args.vendor, manifest_path)
    if no_key_path:
        LOGGER.info("[%s] No-merge-key XMind copy written to %s", args.vendor, no_key_path)
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
