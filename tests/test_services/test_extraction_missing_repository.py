"""A repository whose folder is gone (or lists no file) runs no extraction step: a step that runs would sweep its earlier
output, and the graph would lose everything but what the first steps rebuilt from nothing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deriva.services.extraction import run_extraction, run_extraction_iter


def _run(repo_path, iterate: bool):
    repo = SimpleNamespace(name="demo", path=str(repo_path), url="https://example.com/demo.git", branch="main")
    cfg = SimpleNamespace(node_type="Directory", extraction_method="structural", input_sources=None, enabled=True, sequence=1)
    with (
        patch("deriva.services.extraction.RepoManager") as repos,
        patch("deriva.services.extraction.config.get_extraction_configs", return_value=[cfg]),
        patch("deriva.services.extraction.config.get_file_types", return_value=[]),
        patch("deriva.services.extraction.config.get_excluded_directories", return_value=[".git"]),
        patch("deriva.services.extraction._run_extraction_step") as step,
    ):
        repos.return_value.list_repositories.return_value = [repo]
        if iterate:
            updates = list(run_extraction_iter(MagicMock(), MagicMock(), repo_name="demo"))
            result = updates[-1].stats
        else:
            result = run_extraction(MagicMock(), MagicMock(), repo_name="demo")
    return result, step


@pytest.mark.parametrize("iterate", [False, True])
def test_a_missing_folder_runs_no_step(tmp_path, iterate):
    result, step = _run(tmp_path / "gone", iterate)

    step.assert_not_called()
    text = " ".join(result["errors"])
    assert "Repository folder not found" in text and str(tmp_path / "gone") in text and "\\\\?\\" not in text


@pytest.mark.parametrize("iterate", [False, True])
def test_a_folder_without_files_runs_no_step(tmp_path, iterate):
    (tmp_path / "empty").mkdir()

    result, step = _run(tmp_path / "empty", iterate)

    step.assert_not_called()
    assert "no files to extract" in " ".join(result["errors"])


def test_the_run_fails(tmp_path):
    result, _ = _run(tmp_path / "gone", iterate=False)

    assert result["success"] is False
