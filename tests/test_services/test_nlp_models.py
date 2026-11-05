"""Fetching the NLP models ahead of a run (deriva-cli nlp fetch): one download of the pinned models, sizes reported."""

from __future__ import annotations

import zipfile
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from deriva.cli.cli import app
from deriva.services import nlp_models


def test_fetch_downloads_into_the_models_folder_and_reports_sizes(tmp_path):
    def download(self):
        (self.models_dir / "en_core_web_sm-3.8.0").mkdir(parents=True)
        (self.models_dir / "en_core_web_sm-3.8.0" / "model.bin").write_bytes(b"x" * 2048)
        # Something else in the folder is no model
        (self.models_dir / "old-download").mkdir()
        (self.models_dir / "old-download" / "left.bin").write_bytes(b"x" * 99)
        return {"en": self.models_dir / "en_core_web_sm-3.8.0"}

    with patch("deriva.adapters.nlp.NlpTool.ensure_models", download):
        result = nlp_models.fetch(tmp_path / "nlp")

    assert result["models_dir"] == str(tmp_path / "nlp")
    assert result["models"] == {"en_core_web_sm-3.8.0": 2048}


def test_the_command_prints_each_model_and_the_total():
    with patch("deriva.cli.commands.nlp.nlp_models.fetch", return_value={"models_dir": "/home/nlp", "models": {"a": 3_000_000, "b": 1_000_000}}):
        result = CliRunner().invoke(app, ["nlp", "fetch"])

    assert result.exit_code == 0
    lines = [line.split() for line in result.output.splitlines()]
    assert "/home/nlp" in result.output and ["a", "3.0", "MB"] in lines and ["b", "1.0", "MB"] in lines and ["total", "4.0", "MB"] in lines


def test_a_failed_download_exits_1():
    with patch("deriva.cli.commands.nlp.nlp_models.fetch", side_effect=OSError("network unreachable")):
        result = CliRunner().invoke(app, ["nlp", "fetch"])

    assert result.exit_code == 1 and "network unreachable" in result.output


@pytest.mark.parametrize("failure", [ValueError("SHA-256 of x is y, expected z"), zipfile.BadZipFile("not a zip")])
def test_a_bad_download_is_an_error_message(failure):
    with patch("deriva.cli.commands.nlp.nlp_models.fetch", side_effect=failure):
        result = CliRunner().invoke(app, ["nlp", "fetch"])
    assert result.exit_code == 1 and "Error:" in result.output and not isinstance(result.exception, type(failure))
