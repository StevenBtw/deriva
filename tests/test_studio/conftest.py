"""Fixtures for the studio API: a fake session, never the real databases."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient


class FakeSession:
    """Stands in for PipelineSession: records calls, returns canned values from ``returns``."""

    def __init__(self, connect_error: Exception | None = None, **returns: Any) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.returns: dict[str, Any] = returns
        self.connect_error = connect_error
        self.connected = False

    def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            value = self.returns.get(name)
            return value(*args, **kwargs) if callable(value) else value

        return method

    def called(self, name: str) -> list[tuple[tuple, dict]]:
        return [(a, k) for n, a, k in self.calls if n == name]


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def make_client() -> Iterator[Callable[[FakeSession], TestClient]]:
    from deriva.studio.app import create_app
    from deriva.studio.provider import SessionProvider

    clients: list[TestClient] = []

    def make(session: FakeSession) -> TestClient:
        client = TestClient(create_app(provider=SessionProvider(factory=lambda: session), static_dir=None))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client, fake_session) -> TestClient:
    return make_client(fake_session)
