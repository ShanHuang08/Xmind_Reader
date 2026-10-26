"""Unified CLI entry point for XMind, vendor documents, and test case generation."""

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
            "Build Codex-friendly knowledge files from XMind test maps, "
            "Confluence-exported vendor documents, PDFs, API doc URLs, or generated XMind test cases."
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

  Convert and normalize a PDF, then read canonical Markdown (new isolated flow):
    python main.py read --input Vendor_API.pdf --vendor NewVendor

  Read local HTML or a remote API document through the same flow:
    python main.py read --input exported.html --source-url https://vendor.example/docs --vendor NewVendor
    python main.py read --url https://vendor.example/docs --vendor NewVendor --timeout 30

  Run one stage at a time (use the artifact paths returned by each command):
    python main.py read --input Vendor_API.pdf --vendor NewVendor --stage convert
    python main.py read --input saved/converted.md --vendor NewVendor --stage normalize
    python main.py read --input saved/full_text.md --stage read

  Export converted Markdown for human/AI review:
    python main.py read --input saved/converted.md --vendor NewVendor --stage normalize --export-review

  Generate draft JSON, structured test cases, and final XMind:
    python main.py generate --vendor Esoterica

  Read a new vendor and generate its test-case XMind:
    python main.py new-vendor Veligames

Output folders:
  xmind reader -> xmind_detail/<Vendor>/
  doc reader   -> new_vendor_detail/<Vendor>/
  read         -> new_vendor_detail/<Vendor>/vendor_markdown/ (versioned artifacts)
  generate     -> output/<Vendor>/draft_test_cases.json and output/<Vendor>/<Vendor>_test_cases.xmind

The new read flow does not feed generate/new-vendor automatically.
Exit code 3 from read means partial output or review is needed.
See MARKDOWN_READER_USAGE.md for installation, artifact paths, and review import.
""",
    )
    subparsers = parser.add_subparsers(dest="reader", metavar="{xmind,doc,read,generate,new-vendor}")
    from MarkItDown_reader_main import build_parser as build_document_parser

    build_document_parser(subparsers.add_parser("read", help="Isolated PDF/HTML → canonical Markdown pipeline"))
    _add_xmind_parser(subparsers)
    _add_doc_parser(subparsers)
    _add_generate_parser(subparsers)
    _add_new_vendor_parser(subparsers)
    parsed = parser.parse_args(args)

    if parsed.reader is None:
        parser.print_help()
        return 0

    if parsed.reader == "read":
        from MarkItDown_reader_main import run as run_markitdown_reader

        return run_markitdown_reader(parsed, parser)

    if parsed.reader == "xmind":
        from xmind_reader_main import main as xmind_main

        return xmind_main(_forward_args(parsed))

    if parsed.reader == "new-vendor":
        from new_vendor_main import main as new_vendor_main

        forwarded = [parsed.vendor]
        forwarded.extend(
            _forward_args(
                parsed,
                names=("input_root", "xmind_detail", "vendor_detail", "output", "log_level", "force"),
            )
        )
        return new_vendor_main(forwarded)

    if parsed.reader == "doc":
        from doc_reader_main import main as doc_main

        return doc_main(_forward_args(parsed))

    from generator_main import main as generator_main

    return generator_main(
        _forward_args(
            parsed,
            names=(
                "vendor",
                "vendor_detail",
                "output",
                "xmind_detail",
                "human_xmind",
                "show_case_id",
                "no_merge_key_copy",
                "log_level",
            ),
        )
    )


def _add_xmind_parser(subparsers: argparse._SubParsersAction) -> None:
    xmind = subparsers.add_parser(
        "xmind",
        help="Parse XMind files from input_xmind/ into xmind_detail/<Vendor>/",
        description="Parse XMind test maps into Codex-friendly knowledge chunks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py xmind
  python main.py xmind --input VendorName_test_cases.xmind
  python main.py xmind --input input_xmind/VendorName_test_cases.xmind --vendor VendorName
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
    xmind.add_argument(
        "--force",
        action="store_true",
        help="Regenerate XMind JSON/knowledge files even when the updated map is smaller.",
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
  python main.py doc --input Vendor_VendorName.doc
  python main.py doc --input new_vendor_source/Vendor_VendorName.doc --vendor VendorName
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
    doc.add_argument("--force", action="store_true", help="Force regeneration even if source file is unchanged.")
    doc.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")


def _add_generate_parser(subparsers: argparse._SubParsersAction) -> None:
    generate = subparsers.add_parser(
        "generate",
        help="Generate output/<Vendor>/draft_test_cases.json and output/<Vendor>/<Vendor>_test_cases.xmind",
        description=(
            "Build a draft JSON scaffold from new_vendor_detail/<Vendor>/, generate structured "
            "test cases, write the final XMind file, and validate it by reading it back."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py generate --vendor Esoterica
  python main.py generate --vendor Esoterica --vendor-detail new_vendor_detail --output output
  python main.py generate --vendor Esoterica --human-xmind our_copy/Esoterica_test_cases.xmind
  python main.py generate --vendor Esoterica --human-xmind our_copy/Esoterica_test_cases.xmind --no-merge-key-copy
""",
    )
    generate.add_argument("--vendor", required=True, help="Vendor folder name.")
    generate.add_argument(
        "--vendor-detail",
        default="new_vendor_detail",
        help="Folder containing parsed vendor details. Default: new_vendor_detail",
    )
    generate.add_argument("--output", default="output", help="Output root folder. Default: output")
    generate.add_argument(
        "--xmind-detail",
        default="xmind_detail",
        help="Reference XMind detail root. Default: xmind_detail",
    )
    generate.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")
    generate.add_argument(
        "--human-xmind",
        default="",
        help="Optional human-edited XMind copy to merge before writing the final XMind.",
    )
    generate.add_argument(
        "--show-case-id",
        action="store_true",
        help="Debug option: write visible ID topics for stable_case_id values.",
    )
    generate.add_argument(
        "--no-merge-key-copy",
        action="store_true",
        help="Also export a delivery XMind copy with visible merge_key topics removed.",
    )


def _add_new_vendor_parser(subparsers: argparse._SubParsersAction) -> None:
    from new_vendor_main import build_new_vendor_parser

    new_vendor = subparsers.add_parser(
        "new-vendor",
        help="Read a vendor document and generate its test-case XMind.",
        description="Find inputs recursively, read User Behavior and vendor docs, then generate and validate XMind.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py new-vendor Veligames
  python3 main.py new-vendor Veligames --input-root .
  python main.py new-vendor Veligames --force
""",
    )
    build_new_vendor_parser(new_vendor)


def _forward_args(
    parsed: argparse.Namespace,
    names: tuple[str, ...] = ("input", "output", "vendor", "force", "log_level"),
) -> list[str]:
    forwarded = []
    for name in names:
        value = getattr(parsed, name, None)
        if value in (None, "", False):
            continue
        option = f"--{name.replace('_', '-')}"
        if value is True:
            forwarded.append(option)
        else:
            forwarded.extend([option, str(value)])
    return forwarded


if __name__ == "__main__":
    raise SystemExit(main())
