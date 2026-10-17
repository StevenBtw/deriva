"""Benchmark export bundle: the session folder plus config snapshot and environment, with a sha256 manifest."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from deriva.services.export_bundle import environment_info, export_session, public_model_config, source_digest, verify_bundle

EXTRAS = {"config_snapshot.json": {"versions": {"extraction": {"Repository": 1}}}, "environment.json": {"python": "3.14.0"}}


def make_session(tmp_path):
    session = tmp_path / "benchmarks" / "bench_1"
    (session / "ocel").mkdir(parents=True)
    (session / "llm").mkdir()
    (session / "ocel" / "benchmark_events.jsonl").write_text('{"activity": "StartRun"}\n', encoding="utf-8")
    (session / "llm" / "bench_1_r_m_1.jsonl").write_text('{"call_id": "c1"}\n', encoding="utf-8")
    (session / "session_metadata.json").write_text('{"session_id": "bench_1"}', encoding="utf-8")
    return session


def test_bundle_holds_session_files_extras_and_a_manifest_of_them(tmp_path):
    session = make_session(tmp_path)

    manifest = export_session(session, tmp_path / "out.zip", EXTRAS)

    with zipfile.ZipFile(tmp_path / "out.zip") as bundle:
        names = bundle.namelist()
        assert names == [
            "bench_1/llm/bench_1_r_m_1.jsonl",
            "bench_1/ocel/benchmark_events.jsonl",
            "bench_1/session_metadata.json",
            "config_snapshot.json",
            "environment.json",
            "manifest.json",
        ]
        files = {f["path"]: f for f in manifest["files"]}
        assert list(files) == names[:-1]
        for name, entry in files.items():
            data = bundle.read(name)
            assert (entry["sha256"], entry["size"]) == (hashlib.sha256(data).hexdigest(), len(data))
        assert json.loads(bundle.read("manifest.json")) == manifest
        assert json.loads(bundle.read("environment.json")) == {"python": "3.14.0"}
    assert manifest["session_id"] == "bench_1"


def test_the_same_session_exports_to_identical_bytes(tmp_path):
    session = make_session(tmp_path)

    export_session(session, tmp_path / "a.zip", EXTRAS)
    export_session(session, tmp_path / "b.zip", EXTRAS)

    assert (tmp_path / "a.zip").read_bytes() == (tmp_path / "b.zip").read_bytes()


def test_verify_reports_changed_and_missing_files(tmp_path):
    session = make_session(tmp_path)
    export_session(session, tmp_path / "out.zip", EXTRAS)
    assert verify_bundle(tmp_path / "out.zip") == []

    with zipfile.ZipFile(tmp_path / "out.zip") as original, zipfile.ZipFile(tmp_path / "tampered.zip", "w") as tampered:
        for name in original.namelist():
            if name == "bench_1/ocel/benchmark_events.jsonl":
                continue
            data = b"{}" if name == "bench_1/session_metadata.json" else original.read(name)
            tampered.writestr(name, data)

    assert verify_bundle(tmp_path / "tampered.zip") == ["bench_1/ocel/benchmark_events.jsonl: missing", "bench_1/session_metadata.json: sha256 differs"]


def test_a_missing_session_writes_nothing(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_session(tmp_path / "benchmarks" / "nope", tmp_path / "out.zip", EXTRAS)

    assert not (tmp_path / "out.zip").exists()


def test_the_bundle_cannot_be_written_into_its_own_session(tmp_path):
    session = make_session(tmp_path)

    with pytest.raises(ValueError):
        export_session(session, session / "export.zip", EXTRAS)

    assert not (session / "export.zip").exists()


def test_model_configs_keep_no_secrets():
    config = {"name": "m", "provider": "azure", "model": "gpt", "api_url": "https://example.test", "api_key": "sk-secret", "api_key_env": "AZURE_KEY", "auth_token": "t"}

    assert public_model_config(config) == {"name": "m", "provider": "azure", "model": "gpt", "api_url": "https://example.test", "api_key_env": "AZURE_KEY"}


def test_generation_limits_are_not_taken_for_secrets():
    """max_tokens names a token count, not a token: it belongs in the record."""
    config = {"name": "m", "max_tokens": 4000, "auth_token": "t", "secret_key": "s", "password": "p", "access_token": "a"}

    assert public_model_config(config) == {"name": "m", "max_tokens": 4000}


def test_environment_names_versions_platform_and_models(tmp_path):
    env = environment_info(models={"m": {"name": "m", "provider": "azure", "model": "gpt", "api_key": "sk-secret"}}, repo_root=tmp_path)

    assert {"deriva", "grafeo", "solvor", "python", "platform", "git", "source", "models"} <= set(env)
    assert env["git"] == {"commit": None, "dirty": None}
    assert env["models"] == {"m": {"name": "m", "provider": "azure", "model": "gpt"}}
    assert "sk-secret" not in json.dumps(env)


def test_the_source_digest_identifies_the_code_that_ran(tmp_path):
    """Sessions run on uncommitted trees too, where a commit id alone does not name the code."""
    package = tmp_path / "pkg"
    (package / "sub").mkdir(parents=True)
    (package / "__pycache__").mkdir()
    (package / "a.py").write_text("x = 1\n", encoding="utf-8")
    (package / "sub" / "b.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (package / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"\x00")

    first = source_digest(package)
    (package / "__pycache__" / "a.cpython-314.pyc").write_bytes(b"\x01")  # caches are not code
    unchanged = source_digest(package)
    (package / "a.py").write_text("x = 2\n", encoding="utf-8")
    changed = source_digest(package)

    assert first["files"] == 2
    assert unchanged == first
    assert changed["sha256"] != first["sha256"]


def test_the_source_digest_spans_every_part_of_the_namespace(tmp_path):
    """deriva is one namespace over three packages: moving a subpackage between them keeps the digest."""
    one = tmp_path / "one"
    (one / "core").mkdir(parents=True)
    (one / "studio").mkdir()
    (one / "core" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (one / "studio" / "b.py").write_text("b = 1\n", encoding="utf-8")
    core, member = tmp_path / "core-root", tmp_path / "member-root"
    (core / "core").mkdir(parents=True)
    (member / "studio").mkdir(parents=True)
    (core / "core" / "a.py").write_text("a = 1\n", encoding="utf-8")
    (member / "studio" / "b.py").write_text("b = 1\n", encoding="utf-8")

    assert source_digest([core, member]) == source_digest(one)
    assert source_digest(one)["files"] == 2


def test_the_environment_names_the_installed_deriva_version(tmp_path):
    from deriva.services import about

    assert environment_info(repo_root=tmp_path)["deriva"] == about.version()


def test_links_in_the_session_folder_are_not_followed(tmp_path):
    """A link in a session folder can point anywhere (a file with keys): its target never enters the bundle."""
    import os

    session = make_session(tmp_path)
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "keys.txt").write_text("api key", encoding="utf-8")
    try:
        os.symlink(outside / "keys.txt", session / "link.txt")
        os.symlink(outside, session / "linked", target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links need extra rights on this system")

    manifest = export_session(session, tmp_path / "out.zip", EXTRAS)

    assert not [f["path"] for f in manifest["files"] if "link" in f["path"]]
    with zipfile.ZipFile(tmp_path / "out.zip") as bundle:
        assert all(b"api key" not in bundle.read(name) for name in bundle.namelist())


def test_the_code_commit_of_a_clean_and_a_changed_checkout(tmp_path):
    """The commit and whether the working tree has changes; outside a checkout both are None."""
    import subprocess

    from deriva.services.export_bundle import code_commit

    assert code_commit(tmp_path) == {"commit": None, "dirty": None}
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    git("init", "-q")
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    git("add", "a.txt")
    git("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "one")
    head = git("rev-parse", "HEAD")

    assert code_commit(tmp_path) == {"commit": head, "dirty": False}
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")
    assert code_commit(tmp_path) == {"commit": head, "dirty": True}
