"""Links in a cloned repository never reach files outside it (a link to the user's .env would send its keys to the LLM)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from deriva.common.file_utils import is_inside
from deriva.modules.extraction.file import extract_files
from deriva.services.extraction import _read_documents, list_repo_files


def _link_dir(target: Path, link: Path) -> None:
    """A directory link: a symlink, or on Windows without the symlink privilege a junction (which needs none)."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def _link_file(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("file symlinks need a privilege this machine lacks")


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    outside = tmp_path / "home"
    outside.mkdir()
    (outside / ".env").write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "README.md").write_text("# Docs\n", encoding="utf-8")
    return repo, outside


class TestIsInside:
    def test_a_plain_file_is_inside(self, layout):
        repo, _ = layout
        assert is_inside(repo / "docs" / "README.md", repo)

    def test_a_file_through_a_linked_directory_is_not(self, layout):
        repo, outside = layout
        _link_dir(outside, repo / "docs" / "home")
        assert not is_inside(repo / "docs" / "home" / ".env", repo)

    def test_a_file_symlink_is_not(self, layout):
        repo, outside = layout
        _link_file(outside / ".env", repo / "docs" / "env.md")
        assert not is_inside(repo / "docs" / "env.md", repo)

    def test_a_dotdot_path_is_not(self, layout):
        repo, _ = layout
        assert not is_inside(repo / ".." / "home" / ".env", repo)


class TestWalks:
    def test_list_repo_files_skips_a_linked_directory(self, layout):
        repo, outside = layout
        _link_dir(outside, repo / "docs" / "home")
        assert list_repo_files(repo, []) == ["docs/README.md"]

    def test_list_repo_files_skips_a_file_symlink(self, layout):
        repo, outside = layout
        _link_file(outside / ".env", repo / "docs" / "env.md")
        assert list_repo_files(repo, []) == ["docs/README.md"]

    def test_file_extraction_skips_a_linked_directory(self, layout):
        repo, outside = layout
        _link_dir(outside, repo / "docs" / "home")
        result = extract_files(str(repo), "repo")
        paths = {n["properties"]["path"] for n in result["data"]["nodes"]}
        assert paths == {"docs/README.md"}


class TestReads:
    def test_documents_are_not_read_through_a_link(self, layout):
        repo, outside = layout
        _link_dir(outside, repo / "docs" / "home")
        documents, errors = _read_documents(repo, [{"path": "docs/home/.env"}, {"path": "docs/README.md"}], "repo")
        assert [d["path"] for d in documents] == ["docs/README.md"]
        assert all("secret" not in d["text"] for d in documents)
        assert any("docs/home/.env" in e for e in errors)
