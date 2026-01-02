"""Compatibility wrapper for running the Marimo app from repo root."""

from __future__ import annotations

from deriva.app.app import app


def main() -> int:
    """Console entry point for running the Marimo app."""
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
