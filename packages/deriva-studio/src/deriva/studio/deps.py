"""FastAPI dependencies of the studio."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import Request


def get_session(request: Request) -> Iterator[Any]:
    """The studio's PipelineSession, held for the duration of the request."""
    with request.app.state.provider.session() as session:
        yield session
