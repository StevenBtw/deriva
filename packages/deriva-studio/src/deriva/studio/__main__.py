"""deriva: start the studio on this machine and open it in the browser."""

from __future__ import annotations

import argparse
import secrets
import threading
import time
import webbrowser
from typing import Any

import uvicorn

from deriva.services import about
from deriva.studio.app import create_app
from deriva.studio.guard import AUTH_PATH

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
    parser.add_argument("--allow-remote", action="store_true", help="Allow a --host other machines can reach (anyone with the launch link can use the studio)")
    args = parser.parse_args(argv)
    if args.host not in LOCAL_HOSTS:
        if not args.allow_remote:
            parser.error(f"--host {args.host} makes the studio reachable from other machines, and it has no login; add --allow-remote to do so")
        print(f"Warning: the studio is reachable from other machines on {args.host}; anyone with the launch link can use it.")
    # A fresh token per launch: only the link below opens the studio, so another site's page in the browser cannot
    # drive it; bound to this machine, it also answers to its local names only (DNS rebinding)
    token = secrets.token_urlsafe(32)
    local = args.host in LOCAL_HOSTS
    app = create_app(token=token, allowed_hosts=LOCAL_HOSTS if local else None)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))
    _stop_runs_on_exit(server, app)
    browser_host = "localhost" if local else f"[{args.host}]" if ":" in args.host else args.host
    url = f"http://{browser_host}:{args.port}{AUTH_PATH}?token={token}"
    print(f"Deriva Studio: {url}", flush=True)  # also when stdout is a file or a pipe (a service, a log)
    if not args.no_browser:
        _open_when_ready(server, url)
    server.run()


if __name__ == "__main__":
    main()
