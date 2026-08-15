"""Backward-compatible launcher for ``python main.py new-vendor``."""

from __future__ import annotations

import sys

from main import main


if __name__ == "__main__":
    raise SystemExit(main(["new-vendor", *sys.argv[1:]]))
