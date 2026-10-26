"""Entry point so that ``python -m barnes_ui`` starts the application."""

from __future__ import annotations

import sys


def main() -> int:
    from .app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
