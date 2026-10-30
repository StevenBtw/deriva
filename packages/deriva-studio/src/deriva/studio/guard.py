"""The request guard: a web page open in the user's browser must not drive the local studio.

Three checks, in a plain ASGI middleware (it leaves the event streams of runs untouched):
- Host: a studio bound to this machine answers only to its local names, so a page that rebinds its own domain to
  127.0.0.1 (DNS rebinding) is refused;
- Origin: a request that changes state from another site's page is refused (CSRF);
- token: the server paths need the launch token, from the cookie the launch link sets or an ``X-Deriva-Token`` header.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Awaitable, Callable, Collection
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlsplit

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

AUTH_PATH = "/api/auth"
TOKEN_HEADER = "x-deriva-token"
# The paths the server answers itself (each a whole first segment); the front end's page and bundles load without the token
SERVER_ROOTS = frozenset({"api", "grafeo", "widgets", "docs", "redoc", "openapi.json"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
NO_TOKEN = "Open the studio from the link the deriva command printed: it carries this launch's token"


def host_name(host: str) -> str:
    """The name in a Host header, without its port (``[::1]:8765`` gives ``::1``)."""
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def cookie_name(port: int | None) -> str:
    """One cookie per port: cookies are not kept apart by port, two studios on one machine would share one."""
    return f"deriva_studio_{port or 0}"


class Guard:
    """Wraps the studio app; ``token`` None (an app built by tests or embedded) checks Host and Origin only."""

    def __init__(self, app: ASGIApp, token: str | None, allowed_hosts: Collection[str] | None) -> None:
        self.app = app
        self.token = token
        self.allowed_hosts = {h.lower() for h in allowed_hosts} if allowed_hosts is not None else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            # The studio has no websocket routes: none is opened, from any page
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if self.allowed_hosts is not None and host_name(host).lower() not in self.allowed_hosts:
            await _answer(send, 400, {"detail": "Unknown host: the studio answers on this machine's local names only"})
            return
        origin = headers.get("origin")
        if scope.get("method", "GET") in UNSAFE_METHODS and origin is not None and urlsplit(origin).netloc.lower() != host.lower():
            await _answer(send, 403, {"detail": "A request from another site may not change the studio"})
            return
        path = scope.get("path", "")
        if self.token is None:
            await self.app(scope, receive, send)
            return
        port = (scope.get("server") or (None, None))[1]
        if path == AUTH_PATH:
            await self._sign_in(scope, send, port)
            return
        if path.lstrip("/").split("/", 1)[0] in SERVER_ROOTS and not self._has_token(headers, port):
            await _answer(send, 401, {"detail": NO_TOKEN})
            return
        await self.app(scope, receive, send)

    def _has_token(self, headers: dict[str, str], port: int | None) -> bool:
        assert self.token is not None
        cookies = SimpleCookie(headers.get("cookie", ""))
        given = headers.get(TOKEN_HEADER) or (cookies[cookie_name(port)].value if cookie_name(port) in cookies else "")
        return hmac.compare_digest(given.encode(), self.token.encode())

    async def _sign_in(self, scope: Scope, send: Send, port: int | None) -> None:
        """The launch link: a matching token becomes a cookie, then the page opens without the token in its URL."""
        assert self.token is not None
        given = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token", [""])[0]
        if not hmac.compare_digest(given.encode(), self.token.encode()):
            await _answer(send, 401, {"detail": NO_TOKEN})
            return
        cookie = f"{cookie_name(port)}={self.token}; Path=/; HttpOnly; SameSite=Strict"
        await send({"type": "http.response.start", "status": 303, "headers": [(b"location", b"/"), (b"set-cookie", cookie.encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})


async def _answer(send: Send, status: int, content: dict[str, Any]) -> None:
    body = json.dumps(content).encode()
    await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
