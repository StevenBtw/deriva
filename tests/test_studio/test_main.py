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


def test_the_first_exit_signal_stops_the_runs_before_uvicorn_waits_for_streams():
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, patch("deriva.studio.__main__.create_app") as create_app:
        uvicorn_exit = uvicorn.Server.return_value.handle_exit
        main(["--no-browser"])

    uvicorn.Server.return_value.handle_exit(2, None)

    create_app.return_value.state.runs.shutdown.assert_called_once_with()
    uvicorn_exit.assert_called_once_with(2, None)


def test_main_serves_on_localhost_by_default_and_opens_the_browser():
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, patch("deriva.studio.__main__._open_when_ready") as opener:
        main([])

    assert uvicorn.Config.call_args.kwargs["host"] == "127.0.0.1"
    assert uvicorn.Config.call_args.kwargs["port"] == 8765
    uvicorn.Server.return_value.run.assert_called_once()
    assert opener.call_args.args[1].startswith("http://localhost:8765/api/auth?token=")


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


def test_a_network_address_needs_allow_remote(tmp_path):
    """The studio has no login: binding beyond this machine is an explicit choice, also with TLS."""
    import pytest

    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, pytest.raises(SystemExit):
        main(["--host", "0.0.0.0", "--no-browser", *_certificate(tmp_path)])
    uvicorn.Server.return_value.run.assert_not_called()


def _certificate(tmp_path):
    (tmp_path / "cert.pem").write_text("cert", encoding="utf-8")
    (tmp_path / "key.pem").write_text("key", encoding="utf-8")
    return ["--tls-cert", str(tmp_path / "cert.pem"), "--tls-key", str(tmp_path / "key.pem")]


def test_a_network_address_without_tls_is_refused():
    """The launch link carries the token: over plain HTTP anyone on the network could read it and use the studio."""
    import pytest

    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn, pytest.raises(SystemExit):
        main(["--host", "0.0.0.0", "--allow-remote", "--no-browser"])
    uvicorn.Server.return_value.run.assert_not_called()


def test_a_network_address_with_tls_serves_https(tmp_path, capsys):
    from deriva.studio.__main__ import main

    tls = _certificate(tmp_path)
    with patch("deriva.studio.__main__.uvicorn") as uvicorn:
        main(["--host", "0.0.0.0", "--allow-remote", "--no-browser", *tls])
    config = uvicorn.Config.call_args.kwargs
    assert config["host"] == "0.0.0.0"
    assert config["ssl_certfile"] == tls[1] and config["ssl_keyfile"] == tls[3]
    uvicorn.Server.return_value.run.assert_called_once()


def test_a_wildcard_host_prints_a_link_with_the_machine_s_name(tmp_path, capsys):
    """0.0.0.0 is no address another machine can open, and no certificate names it: the link uses the machine's name."""
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn"), patch("deriva.studio.__main__.socket.gethostname", return_value="studio-host"):
        main(["--host", "0.0.0.0", "--allow-remote", "--no-browser", *_certificate(tmp_path)])
        out = capsys.readouterr().out
        main(["--host", "::", "--allow-remote", "--no-browser", *_certificate(tmp_path)])
        out_v6 = capsys.readouterr().out
    assert "Deriva Studio: https://studio-host:8765/api/auth?token=" in out and "0.0.0.0:8765" not in out
    assert "the name your certificate is issued for" in out
    assert "Deriva Studio: https://studio-host:8765/api/auth?token=" in out_v6


def test_a_named_remote_host_keeps_its_name_in_the_link(tmp_path, capsys):
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn"):
        main(["--host", "192.0.2.10", "--allow-remote", "--no-browser", *_certificate(tmp_path)])
    assert "Deriva Studio: https://192.0.2.10:8765/api/auth?token=" in capsys.readouterr().out


def test_tls_on_this_machine_needs_no_allow_remote(tmp_path, capsys):
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn"):
        main(["--no-browser", *_certificate(tmp_path)])
    assert "Deriva Studio: https://localhost:8765/api/auth?token=" in capsys.readouterr().out


def test_this_machine_stays_plain_http_without_a_certificate(capsys):
    from deriva.studio.__main__ import main

    with patch("deriva.studio.__main__.uvicorn") as uvicorn:
        main(["--no-browser"])
    assert "ssl_certfile" not in uvicorn.Config.call_args.kwargs
    assert "Deriva Studio: http://localhost:8765/api/auth?token=" in capsys.readouterr().out


def test_a_certificate_needs_its_key_and_both_must_exist(tmp_path):
    import pytest

    from deriva.studio.__main__ import main

    tls = _certificate(tmp_path)
    for arguments in (tls[:2], tls[2:], ["--tls-cert", str(tmp_path / "missing.pem"), tls[2], tls[3]], [tls[0], tls[1], "--tls-key", str(tmp_path / "missing.pem")]):
        with patch("deriva.studio.__main__.uvicorn") as uvicorn, pytest.raises(SystemExit):
            main(["--no-browser", *arguments])
        uvicorn.Server.return_value.run.assert_not_called()


def test_the_api_namespaces_themselves_are_no_front_end_routes(tmp_path):
    (tmp_path / "index.html").write_text("<html>studio</html>", encoding="utf-8")
    client = TestClient(make_app(tmp_path))

    assert [client.get(path).status_code for path in ("/api", "/grafeo", "/widgets")] == [404, 404, 404]
