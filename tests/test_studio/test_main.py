"""Entry point and static front-end serving."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_studio.conftest import FakeSession


def make_app(static_dir):
    from deriva.studio.app import create_app
    from deriva.studio.provider import SessionProvider

    return create_app(provider=SessionProvider(factory=lambda: FakeSession()), static_dir=static_dir)


def test_built_front_end_is_served_with_a_single_page_fallback(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    client = TestClient(make_app(tmp_path))

    assert client.get("/").text == "<html>studio</html>"
    assert client.get("/workspace/benchmark").text == "<html>studio</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/nope").headers["content-type"].startswith("application/json")


def test_without_a_build_the_root_explains_how_to_build(tmp_path):
    client = TestClient(make_app(tmp_path / "missing"))

    response = client.get("/")

    assert response.status_code == 200
    assert "npm run build" in response.text


def test_main_runs_uvicorn_on_localhost_by_default():
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn.run") as run:
        main([])

    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 8765


def test_main_takes_host_and_port():
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn.run") as run:
        main(["--port", "9000"])

    assert run.call_args.kwargs["port"] == 9000
