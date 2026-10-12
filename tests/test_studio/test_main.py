"""Entry point and static front-end serving."""

from __future__ import annotations

import os
from types import SimpleNamespace
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


def test_the_page_is_revalidated_so_an_upgrade_never_serves_an_old_bundle(tmp_path):
    """The page names hashed bundles; a cached page after an upgrade would point at bundles that are gone."""
    (tmp_path / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    client = TestClient(make_app(tmp_path))

    assert client.get("/").headers["cache-control"] == "no-cache"
    assert client.get("/workspace/benchmark").headers["cache-control"] == "no-cache"


def test_without_a_build_the_root_explains_how_to_build(tmp_path):
    client = TestClient(make_app(tmp_path / "missing"))

    response = client.get("/")

    assert response.status_code == 200
    assert "npm run build" in response.text


def test_main_serves_on_localhost_by_default_and_opens_the_browser():
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, patch("deriva.studio.__main__._open_when_ready") as opener:
        main([])

    assert uvicorn.Config.call_args.kwargs["host"] == "127.0.0.1"
    assert uvicorn.Config.call_args.kwargs["port"] == 8765
    uvicorn.Server.return_value.run.assert_called_once()
    assert opener.call_args.args[1] == "http://localhost:8765/"


def test_main_takes_host_port_and_no_browser():
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, patch("deriva.studio.__main__._open_when_ready") as opener:
        main(["--port", "9000", "--no-browser"])

    assert uvicorn.Config.call_args.kwargs["port"] == 9000
    opener.assert_not_called()


def test_main_keeps_the_pydantic_ai_banner_out(monkeypatch):
    """The studio sets PYDANTIC_AI_NO_BANNER so the banner stays out of the server's console."""
    monkeypatch.delenv("PYDANTIC_AI_NO_BANNER", raising=False)
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn"), patch("deriva.studio.__main__._open_when_ready"):
        main([])

    assert os.environ["PYDANTIC_AI_NO_BANNER"] == "1"


def test_main_keeps_a_user_set_banner_value(monkeypatch):
    """A value the user set themselves wins (setdefault, not overwrite)."""
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "0")
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn"), patch("deriva.studio.__main__._open_when_ready"):
        main([])

    assert os.environ["PYDANTIC_AI_NO_BANNER"] == "0"


def test_the_browser_opens_once_the_server_has_started():
    from deriva.studio.__main__ import _open_when_ready

    with patch("deriva.studio.__main__.webbrowser.open") as open_url:
        _open_when_ready(SimpleNamespace(started=True, should_exit=False), "http://localhost:8765/").join(5)

    open_url.assert_called_once_with("http://localhost:8765/")


def test_no_browser_when_the_server_stops_before_it_started():
    from deriva.studio.__main__ import _open_when_ready

    with patch("deriva.studio.__main__.webbrowser.open") as open_url:
        _open_when_ready(SimpleNamespace(started=False, should_exit=True), "http://localhost:8765/").join(5)

    open_url.assert_not_called()


def test_a_network_address_needs_allow_remote():
    """The studio has no login: binding beyond this machine is an explicit choice."""
    import pytest

    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, pytest.raises(SystemExit):
        main(["--host", "0.0.0.0", "--no-browser"])
    uvicorn.Server.return_value.run.assert_not_called()

    with patch("deriva.studio.__main__.uvicorn") as uvicorn:
        main(["--host", "0.0.0.0", "--allow-remote", "--no-browser"])
    assert uvicorn.Config.call_args.kwargs["host"] == "0.0.0.0"
    uvicorn.Server.return_value.run.assert_called_once()


def test_the_api_namespaces_themselves_are_no_front_end_routes(tmp_path):
    (tmp_path / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    client = TestClient(make_app(tmp_path))

    assert [client.get(path).status_code for path in ("/api", "/grafeo", "/widgets")] == [404, 404, 404]
