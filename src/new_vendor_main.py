"""One-command orchestration for new vendor test-case generation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from doc_reader_main import main as doc_main
from generator_main import main as generator_main
from pipeline.input_discovery import choose_match, find_vendor_document
from xmind_reader_main import main as xmind_main


def build_new_vendor_parser(
    parser: argparse.ArgumentParser | None = None,
    *,
    wrapper: bool = False,
) -> argparse.ArgumentParser:
    """Build the shared parser for main.py and the standalone wrapper."""
    if parser is None:
        python_command = "python3" if sys.platform == "darwin" else "python"
        example = (
            f"{python_command} run_new_vendor.py Veligames"
            if wrapper
            else "python main.py new-vendor Veligames"
        )
        parser = argparse.ArgumentParser(
            description="Read a new vendor and generate its test-case XMind.",
            epilog=f"Example command: {example}",
        )

    parser.add_argument(
        "vendor",
        help="Vendor name, for example Veligames, CasinoGate, Softgaming.",
    )
    if wrapper:
        return parser

    parser.add_argument("--input-root", default=".", help="Root folder to search recursively. Default: .")
    parser.add_argument("--xmind-detail", default="xmind_detail")
    parser.add_argument("--vendor-detail", default="new_vendor_detail")
    parser.add_argument("--output", default="output")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--force", action="store_true", help="Force document re-reading.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_new_vendor_parser()
    args = parser.parse_args(argv)

    root = Path(args.input_root).resolve()
    behavior_xmind = choose_match(root, "user_behavior_map.xmind")
    vendor_doc = find_vendor_document(root, args.vendor)

    xmind_args = ["--input", str(behavior_xmind), "--output", args.xmind_detail,
                  "--vendor", "User_Behavior_map", "--log-level", args.log_level]
    result = xmind_main(xmind_args)
    if result:
        return result

    doc_args = ["--input", str(vendor_doc), "--output", args.vendor_detail,
                "--vendor", args.vendor, "--log-level", args.log_level]
    if args.force:
        doc_args.append("--force")
    result = doc_main(doc_args)
    if result:
        return result

    generate_args = ["--vendor", args.vendor, "--vendor-detail", args.vendor_detail,
                     "--xmind-detail", args.xmind_detail, "--output", args.output,
                     "--log-level", args.log_level, "--no-merge-key-copy"]
    return generator_main(generate_args)
