"""One PipelineSession for the studio process, used under a lock (DuckDB and grafeo handles are not shared concurrently)."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from deriva.services import PipelineSession

_HELD_MARKERS = ("being used by another process", "File is already open in")
_PID = re.compile(r"\(PID (\d+)\)")


class DatabaseHeld(RuntimeError):
    """Another process (for example a CLI benchmark) holds the config database."""

    def __init__(self, message: str, pid: int | None) -> None:
        super().__init__(message)
        self.pid = pid


class SessionBusy(RuntimeError):
    """A pipeline step holds the session; the request should be retried."""


class SessionProvider:
    """Owns the studio's single PipelineSession; ``session()`` connects lazily and serializes access."""

    def __init__(self, factory: Callable[[], Any] = PipelineSession) -> None:
        self._factory = factory
        self._session: Any | None = None
        self._lock = threading.RLock()
        self.held_by: int | None = None
        self.error: str | None = None

    @contextmanager
    def session(self, wait: float | None = 2.0) -> Iterator[Any]:
        """Yield the connected session; wait up to ``wait`` seconds for the lock (None waits forever)."""
        acquired = self._lock.acquire() if wait is None else self._lock.acquire(timeout=wait)
        if not acquired:
            raise SessionBusy("A pipeline step is running; try again when it finishes")
        try:
            if self._session is None:
                self._session = self._connect()
            yield self._session
        finally:
            self._lock.release()

    def _connect(self) -> Any:
        candidate = self._factory()
        try:
            candidate.connect()
        except Exception as exc:
            text = str(exc)
            if any(marker in text for marker in _HELD_MARKERS):
                match = _PID.search(text)
                self.held_by = int(match.group(1)) if match else None
                self.error = text
                raise DatabaseHeld(text, self.held_by) from exc
            raise
        self.held_by = None
        self.error = None
        return candidate

    def status(self) -> dict[str, Any]:
        """Database ownership as the UI shows it: owned, held (with PID) or not connected."""
        if self._session is not None:
            return {"state": "owned"}
        if self.error is not None:
            return {"state": "held", "held_by": self.held_by, "error": self.error}
        return {"state": "not_connected"}

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.disconnect()
                self._session = None
