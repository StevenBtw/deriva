"""deriva: start the studio on this machine and open it in the browser."""

from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from typing import Any

import uvicorn

from deriva.services import about
from deriva.studio.app import create_app

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def _open_when_ready(server: Any, url: str) -> threading.Thread:
    """Open the studio in the browser once the server accepts connections (never when it stops first)."""

    def wait() -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.1)
        if server.started:
            webbrowser.open(url)

    thread = threading.Thread(target=wait, name="open-browser", daemon=True)
    thread.start()
    return thread


def _stop_runs_on_exit(server: Any, app: Any) -> None:
    """The first Ctrl+C or SIGTERM also cancels the run and ends the event streams: uvicorn waits for open streams
    before it shuts the app down, and a stream lasts until its run ends."""
    handle_exit = server.handle_exit

    def handle(sig: int, frame: Any) -> None:
        app.state.runs.shutdown()
        handle_exit(sig, frame)

    server.handle_exit = handle


def main(argv: list[str] | None = None) -> None:
    # pydantic-ai's first-run banner is noise in the studio's console output
    about.suppress_pydantic_ai_banner()
    parser = argparse.ArgumentParser(prog="deriva", description="Deriva Studio: the local web UI for the pipeline")
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default: 127.0.0.1, this machine only)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the studio in the browser")
    parser.add_argument("--allow-remote", action="store_true", help="Allow a --host other machines can reach (the studio has no login)")
    args = parser.parse_args(argv)
    if args.host not in LOCAL_HOSTS:
        if not args.allow_remote:
            parser.error(f"--host {args.host} makes the studio reachable from other machines, and it has no login; add --allow-remote to do so")
        print(f"Warning: the studio is reachable from other machines on {args.host}; it has no login.")
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))
    _stop_runs_on_exit(server, app)
    if not args.no_browser:
        browser_host = "localhost" if args.host in LOCAL_HOSTS else f"[{args.host}]" if ":" in args.host else args.host
        _open_when_ready(server, f"http://{browser_host}:{args.port}/")
    server.run()


if __name__ == "__main__":
    main()
