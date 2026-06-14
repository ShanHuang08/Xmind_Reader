"""Unified CLI entry point for XMind and vendor document readers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description=(
            "Build Codex-friendly knowledge files from XMind test maps or "
            "Confluence-exported vendor documents."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  List available XMind files and processed status:
    python main.py xmind

  Parse one XMind file from input_xmind/:
    python main.py xmind --input EGTDigital_test_cases.xmind

  Parse one XMind file and force the vendor folder name:
    python main.py xmind --input EGTDigital_test_cases.xmind --vendor EGTDigital

  Parse a Confluence-exported Word/HTML vendor document:
    python main.py doc --input Vendor_Esoterica.doc

  Parse a vendor document and force the vendor folder name:
    python main.py doc --input Vendor_Esoterica.doc --vendor Esoterica

Output folders:
  xmind reader -> xmind_detail/<Vendor>/
  doc reader   -> new_vendor_detail/<Vendor>/
  output/      -> reserved for future AI-generated XMind files
""",
    )
    subparsers = parser.add_subparsers(dest="reader", metavar="{xmind,doc}")
    _add_xmind_parser(subparsers)
    _add_doc_parser(subparsers)
    parsed = parser.parse_args(args)

    if parsed.reader is None:
        parser.print_help()
        return 0

    if parsed.reader == "xmind":
        from xmind_reader_main import main as xmind_main

        return xmind_main(_forward_args(parsed))

    from doc_reader_main import main as doc_main

    return doc_main(_forward_args(parsed))


def _add_xmind_parser(subparsers: argparse._SubParsersAction) -> None:
    xmind = subparsers.add_parser(
        "xmind",
        help="Parse XMind files from input_xmind/ into xmind_detail/<Vendor>/",
        description="Parse XMind test maps into Codex-friendly knowledge chunks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py xmind
  python main.py xmind --input EGTDigital_test_cases.xmind
  python main.py xmind --input input_xmind/EGTDigital_test_cases.xmind --vendor EGTDigital
""",
    )
    xmind.add_argument(
        "--input",
        default=None,
        help=(
            "XMind file, file name under input_xmind, or folder containing .xmind files. "
            "If omitted, input_xmind is scanned and multiple files are listed."
        ),
    )
    xmind.add_argument(
        "--output",
        default="xmind_detail",
        help="Folder for XMind detail files. Default: xmind_detail",
    )
    xmind.add_argument(
        "--vendor",
        default="",
        help="Optional vendor folder name. If omitted, inferred from XMind file name.",
    )
    xmind.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")


def _add_doc_parser(subparsers: argparse._SubParsersAction) -> None:
    doc = subparsers.add_parser(
        "doc",
        help="Parse vendor Word/HTML docs from new_vendor_source/ into new_vendor_detail/<Vendor>/",
        description="Parse Confluence-exported vendor docs into Codex-friendly API details.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py doc --input Vendor_Esoterica.doc
  python main.py doc --input new_vendor_source/Vendor_Esoterica.doc --vendor Esoterica
  python main.py doc --input new_vendor_source
""",
    )
    doc.add_argument(
        "--input",
        default="new_vendor_source",
        help=(
            "Document file, file name under new_vendor_source, or folder containing "
            ".doc/.docx/.html/.htm files. Default: new_vendor_source"
        ),
    )
    doc.add_argument(
        "--output",
        default="new_vendor_detail",
        help="Folder for generated vendor detail files. Default: new_vendor_detail",
    )
    doc.add_argument(
        "--vendor",
        default="",
        help="Optional vendor folder name. If omitted, inferred from document file name.",
    )
    doc.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")


def _forward_args(parsed: argparse.Namespace) -> list[str]:
    forwarded = []
    for name in ("input", "output", "vendor", "log_level"):
        value = getattr(parsed, name, None)
        if value in (None, ""):
            continue
        forwarded.extend([f"--{name.replace('_', '-')}", str(value)])
    return forwarded


if __name__ == "__main__":
    raise SystemExit(main())
