"""Unified MarkItDown conversion, normalization, and Markdown reading CLI."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from urllib.parse import urlsplit


def build_parser(parser=None):
    parser = parser or argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Local PDF, HTML, Markdown, or OpenAPI JSON")
    source.add_argument("--url", help="Remote HTML, Markdown, or OpenAPI JSON")
    parser.add_argument("--vendor", default="", help="Required for new sources; inherited for managed artifacts")
    parser.add_argument("--output", default="new_vendor_detail", help="Root; writes only <vendor>/vendor_markdown")
    parser.add_argument("--stage", choices=("all", "convert", "normalize", "read"), default="all")
    parser.add_argument("--source-url", default="", help="Metadata only for local HTML or ordinary Markdown")
    parser.add_argument("--source-id", default="")
    parser.add_argument("--parent-normalization", help="Parent manifest for edited canonical Markdown")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--converter", choices=("markitdown", "legacy"), default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    review = parser.add_mutually_exclusive_group()
    review.add_argument("--export-review", action="store_true")
    review.add_argument("--import-extraction")
    review.add_argument("--import-candidate")
    parser.add_argument("--review-decisions")
    return parser


def validate_args(args, parser):
    def check(condition, message):
        if not condition:
            parser.error(message)
    check(not args.url or (urlsplit(args.url).scheme in {"http", "https"} and bool(urlsplit(args.url).hostname)), "--url requires HTTP(S)")
    check(not args.url or not (urlsplit(args.url).username or urlsplit(args.url).password), "Use separate authentication options")
    check(args.stage in {"all", "convert"} or not args.url, "normalize/read require local input")
    check(args.url or all(v is None for v in (args.username, args.password, args.timeout)), "Authentication/timeout only apply to --url")
    check(args.timeout is None or args.timeout > 0, "--timeout must be positive")
    check(not args.source_url or (args.input and Path(args.input).suffix.lower() in {".html", ".htm", ".md", ".markdown"}), "--source-url only applies to local HTML/Markdown")
    check(not args.converter or (args.input and Path(args.input).suffix.lower() == ".pdf" and args.stage in {"all", "convert"}), "--converter only applies to local PDF conversion")
    check(not any((args.export_review, args.import_extraction, args.import_candidate, args.parent_normalization)) or args.stage == "normalize", "Review/edit options require --stage normalize")
    check(not args.review_decisions or args.import_candidate, "--review-decisions requires --import-candidate")
    check(not args.import_candidate or args.review_decisions, "--import-candidate requires --review-decisions")
    check(not args.parent_normalization or not any((args.export_review, args.import_extraction, args.import_candidate)), "Parent edit and review import are separate actions")
    if args.input:
        suffix = Path(args.input).suffix.lower()
        check(args.stage not in {"normalize", "read"} or suffix in {".md", ".markdown"}, "normalize/read require Markdown input")
        check(args.stage != "convert" or suffix not in {".md", ".markdown"}, "Local Markdown needs normalize/read, not convert")


def run(args, parser):
    validate_args(args, parser)
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(_QuietPdfFontWarnings())
    from MarkItDown_reader.pipeline import execute
    try:
        code, result = execute(args)
        _print_result(result)
        return code
    except (ValueError, OSError, UnicodeError, RuntimeError, TypeError, KeyError, AttributeError, IndexError) as exc:
        logging.error("Document reader: %s", exc)
        return 1


class _QuietPdfFontWarnings(logging.Filter):
    """Hide repeated, non-fatal font descriptor warnings from PDF conversion."""
    def filter(self, record):
        return "Could not get FontBBox from font descriptor" not in record.getMessage()


def _print_result(result: dict) -> None:
    selection = result.get("endpoint_selection")
    if not isinstance(selection, dict):
        # Conversion and normalization-only stages do not have endpoint results yet.
        print(f"Status: {result.get('status', result.get('normalization_status', 'completed'))}")
        if result.get("full_text"):
            print(f"Full text: {result['full_text']}")
        elif result.get("converted"):
            print(f"Converted: {result['converted']}")
        return

    endpoints = result.get("selected_endpoint_details", [])
    print(f"Endpoints found ({len(endpoints)}):")
    if endpoints:
        for endpoint in endpoints:
            method = endpoint.get("method") or "?"
            path = endpoint.get("endpoint") or "unknown path"
            role = endpoint.get("role") or "unclassified"
            print(f"  - {endpoint.get('name', 'Unnamed')} - {method} {path} [{role}]")
    else:
        print("  - None")
    print(f"Error codes: {result.get('error_code_count', 0)}")
    missing = selection.get("missing_core_roles", [])
    error_code_count = result.get("error_code_count", 0)
    failures = []
    if missing:
        failures.append(f"missing endpoints: {', '.join(missing)}")
    if error_code_count <= 0:
        failures.append("no error codes found")
    if failures:
        print(f"Endpoint check: Failed ({'; '.join(failures)})")
    else:
        print("Endpoint check: Success")


def main(argv=None):
    parser = build_parser()
    return run(parser.parse_args(argv), parser)


if __name__ == "__main__":
    raise SystemExit(main())
