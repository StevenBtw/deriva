"""The studio's request guard: a web page in the user's browser must not drive the local studio (DNS rebinding, CSRF)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_studio.conftest import FakeSession

TOKEN = "launch-token"
LOCAL = ("127.0.0.1", "localhost", "::1")


def guarded(tmp_path, base_url="http://localhost:8765", allowed_hosts=LOCAL, token=TOKEN) -> TestClient:
    from deriva.studio.app import create_app
    from deriva.studio.provider import SessionProvider

    session = FakeSession(get_repositories=[{"name": "deriva"}], clone_repository={"success": True, "name": "x", "path": "p", "url": "u"})
    app = create_app(provider=SessionProvider(factory=lambda: session), static_dir=None, runs_dir=tmp_path / "runs", token=token, allowed_hosts=allowed_hosts)
    return TestClient(app, base_url=base_url, follow_redirects=False)


def signed_in(client: TestClient) -> TestClient:
    response = client.get(f"/api/auth?token={TOKEN}")
    assert response.status_code == 303 and response.headers["location"] == "/"
    return client


class TestToken:
    def test_the_api_needs_the_launch_token(self, tmp_path):
        response = guarded(tmp_path).get("/api/repositories")
        assert response.status_code == 401
        assert "link" in response.json()["detail"]

    def test_the_launch_link_sets_a_strict_http_only_cookie(self, tmp_path):
        client = guarded(tmp_path)
        cookie = client.get(f"/api/auth?token={TOKEN}").headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict") and "Path=/" in cookie
        assert client.get("/api/repositories").json() == [{"name": "deriva"}]

    def test_a_wrong_token_sets_nothing(self, tmp_path):
        client = guarded(tmp_path)
        assert client.get("/api/auth?token=guess").status_code == 401
        assert client.get("/api/repositories").status_code == 401

    def test_scripts_send_the_token_as_a_header(self, tmp_path):
        assert guarded(tmp_path).get("/api/repositories", headers={"X-Deriva-Token": TOKEN}).status_code == 200

    @pytest.mark.parametrize("path", ["/grafeo/query", "/widgets/graph.js", "/docs", "/openapi.json"])
    def test_every_server_path_needs_it(self, tmp_path, path):
        assert guarded(tmp_path).get(path).status_code == 401

    def test_the_page_itself_loads_without_it(self, tmp_path):
        # The front end explains what to do when its API calls answer 401
        assert guarded(tmp_path).get("/").status_code == 200


class TestHost:
    def test_a_rebound_host_name_is_refused(self, tmp_path):
        client = signed_in(guarded(tmp_path))
        assert client.get("/api/repositories", headers={"Host": "attacker.example:8765"}).status_code == 400

    @pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765", "localhost"])
    def test_local_names_pass(self, tmp_path, host):
        client = guarded(tmp_path)
        assert client.get("/api/repositories", headers={"Host": host, "X-Deriva-Token": TOKEN}).status_code == 200

    def test_without_a_host_list_any_host_passes(self, tmp_path):
        """--allow-remote: the machine's name is unknown, the token alone guards the studio."""
        client = guarded(tmp_path, allowed_hosts=None)
        assert client.get("/api/repositories", headers={"Host": "studio.lan:8765", "X-Deriva-Token": TOKEN}).status_code == 200


class TestOrigin:
    def test_a_cross_site_post_is_refused(self, tmp_path):
        client = signed_in(guarded(tmp_path))
        response = client.post("/api/repositories", json={"url": "https://example.org/x.git"}, headers={"Origin": "https://attacker.example"})
        assert response.status_code == 403

    def test_a_same_origin_post_passes(self, tmp_path):
        client = signed_in(guarded(tmp_path))
        response = client.post("/api/repositories", json={"url": "https://example.org/x.git"}, headers={"Origin": "http://localhost:8765"})
        assert response.status_code == 201

    def test_the_origin_check_holds_without_a_token(self, tmp_path):
        """An app built without a token (tests, embedding) still refuses cross-site writes."""
        client = guarded(tmp_path, token=None, allowed_hosts=None)
        assert client.post("/api/repositories/x/update", headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.get("/api/repositories").status_code == 200


class TestLauncher:
    def test_the_launch_link_carries_a_fresh_token(self):
        from unittest.mock import patch

        from deriva.studio.__main__ import main

        with patch("deriva.studio.__main__.uvicorn"), patch("deriva.studio.__main__._open_when_ready") as opener, patch("deriva.studio.__main__.create_app") as create_app:
            main([])
            main([])
        tokens = [c.kwargs["token"] for c in create_app.call_args_list]
        assert len(tokens[0]) >= 32 and tokens[0] != tokens[1]
        assert create_app.call_args_list[0].kwargs["allowed_hosts"] == LOCAL
        assert opener.call_args_list[0].args[1] == f"http://localhost:8765/api/auth?token={tokens[0]}"

    def test_a_remote_studio_checks_no_host_but_still_the_token(self):
        from unittest.mock import patch

        from deriva.studio.__main__ import main

        with patch("deriva.studio.__main__.uvicorn"), patch("deriva.studio.__main__.create_app") as create_app:
            main(["--host", "0.0.0.0", "--allow-remote", "--no-browser"])
        assert create_app.call_args.kwargs["allowed_hosts"] is None
        assert create_app.call_args.kwargs["token"]
