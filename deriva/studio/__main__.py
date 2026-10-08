"""deriva: start the studio on this machine."""

from __future__ import annotations

import argparse

import uvicorn

from deriva.studio.app import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="deriva", description="Deriva Studio: the local web UI for the pipeline")
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default: 127.0.0.1, this machine only)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"Warning: the studio is reachable from other machines on {args.host}; it has no login.")
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
