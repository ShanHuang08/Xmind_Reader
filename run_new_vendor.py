"""Backward-compatible launcher for ``python main.py new-vendor``."""

from __future__ import annotations

import sys

from main import main
from new_vendor_main import build_new_vendor_parser


if __name__ == "__main__":
    parser = build_new_vendor_parser(wrapper=True)
    args = parser.parse_args()
    raise SystemExit(main(["new-vendor", args.vendor]))
