"""Compatibility wrapper for running the CLI as a script."""

from __future__ import annotations

from deriva.cli.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
