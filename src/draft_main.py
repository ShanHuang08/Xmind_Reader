"""CLI for building Codex-facing draft test case JSON scaffolds."""

from __future__ import annotations

import argparse
import logging

from generator.draft_builder import build_draft


LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a draft_test_cases.json scaffold for Codex generation."
    )
    parser.add_argument("--vendor", required=True, help="Vendor folder name under new_vendor_detail.")
    parser.add_argument(
        "--vendor-detail",
        default="new_vendor_detail",
        help="Folder containing parsed vendor details. Default: new_vendor_detail",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Output folder for future generated test case artifacts. Default: output",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    output_path = build_draft(args.vendor, args.vendor_detail, args.output)
    LOGGER.info("[%s] Draft JSON written to %s", args.vendor, output_path)
    return 0
