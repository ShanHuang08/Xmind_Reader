"""Unified CLI entry point for XMind, document, PDF, and draft readers."""

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

  Parse a supplementary vendor API PDF:
    python main.py pdf --pdf EGT_Digital_Integration_API_Spec_v1.28.pdf --vendor EGT_Digital

  Build a Codex-facing draft JSON scaffold for generation:
    python main.py draft --vendor Esoterica

Output folders:
  xmind reader -> xmind_detail/<Vendor>/
  doc reader   -> new_vendor_detail/<Vendor>/
  pdf reader   -> new_vendor_detail/<Vendor>/vendor_pdf/
  draft builder -> output/<Vendor>/draft_test_cases.json
  output/      -> reserved for future AI-generated XMind files
""",
    )
    subparsers = parser.add_subparsers(dest="reader", metavar="{xmind,doc,pdf,draft}")
    _add_xmind_parser(subparsers)
    _add_doc_parser(subparsers)
    _add_pdf_parser(subparsers)
    _add_draft_parser(subparsers)
    parsed = parser.parse_args(args)

    if parsed.reader is None:
        parser.print_help()
        return 0

    if parsed.reader == "xmind":
        from xmind_reader_main import main as xmind_main

        return xmind_main(_forward_args(parsed))

    if parsed.reader == "doc":
        from doc_reader_main import main as doc_main

        return doc_main(_forward_args(parsed))

    if parsed.reader == "pdf":
        from pdf_reader_main import main as pdf_main

        return pdf_main(_forward_args(parsed, names=("pdf", "vendor", "output", "log_level")))

    from draft_main import main as draft_main

    return draft_main(_forward_args(parsed, names=("vendor", "vendor_detail", "output", "log_level")))


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
    doc.add_argument("--force", action="store_true", help="Force regeneration even if source file is unchanged.")
    doc.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")


def _add_pdf_parser(subparsers: argparse._SubParsersAction) -> None:
    pdf = subparsers.add_parser(
        "pdf",
        help="Parse supplementary vendor API PDFs into new_vendor_detail/<Vendor>/vendor_pdf/",
        description=(
            "Parse a supplementary vendor API PDF into validation, Markdown, endpoint index, "
            "and API section chunks. DOC/HTML output remains the primary source."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py pdf --pdf EGT_Digital_Integration_API_Spec_v1.28.pdf --vendor EGT_Digital
  python main.py pdf --pdf C:\\Docs\\Vendor_API.pdf --vendor NewVendor --output new_vendor_detail
  python main.py pdf --pdf Vendor_API.pdf --vendor NewVendor --output new_vendor_detail/NewVendor/vendor_pdf
""",
    )
    pdf.add_argument("--pdf", required=True, help="PDF file path.")
    pdf.add_argument(
        "--vendor",
        default="",
        help="Vendor folder name. If omitted, inferred from PDF file name.",
    )
    pdf.add_argument(
        "--output",
        default="new_vendor_detail",
        help=(
            "Output root folder or direct vendor_pdf folder. Default: new_vendor_detail. "
            "If the path ends with vendor_pdf, it is used directly."
        ),
    )
    pdf.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")


def _add_draft_parser(subparsers: argparse._SubParsersAction) -> None:
    draft = subparsers.add_parser(
        "draft",
        help="Build output/<Vendor>/draft_test_cases.json for Codex generation",
        description=(
            "Build a Codex-facing draft JSON scaffold from new_vendor_detail/<Vendor>/ "
            "without generating final test cases yet."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py draft --vendor Esoterica
  python main.py draft --vendor Esoterica --vendor-detail new_vendor_detail --output output
""",
    )
    draft.add_argument("--vendor", required=True, help="Vendor folder name under new_vendor_detail.")
    draft.add_argument(
        "--vendor-detail",
        default="new_vendor_detail",
        help="Folder containing parsed vendor details. Default: new_vendor_detail",
    )
    draft.add_argument(
        "--output",
        default="output",
        help="Output folder for future generated test case artifacts. Default: output",
    )
    draft.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO")


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
