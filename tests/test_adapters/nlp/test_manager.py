"""The NLP tool adapter: runs `deriva-nlp` in its own environment and exchanges JSON files with it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from deriva.adapters.nlp import NlpTool, NlpToolError


class FakeRunner:
    """Records the command; for `extract` it writes the given result to the --output file."""

    def __init__(self, result=None, returncode=0, stderr=""):
        self.result, self.returncode, self.stderr = result, returncode, stderr
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if "extract" in command and self.returncode == 0:
            request = json.loads(Path(command[command.index("--input") + 1]).read_text(encoding="utf-8"))
            self.request = request
            Path(command[command.index("--output") + 1]).write_text(json.dumps(self.result), encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, stdout="", stderr=self.stderr)


def test_extract_passes_documents_and_settings_and_returns_the_result(tmp_path):
    runner = FakeRunner(result={"candidates": [{"term": "Invoice"}]})
    tool = NlpTool(project_dir=tmp_path / "nlp", models_dir=tmp_path / "models", runner=runner)

    result = tool.extract([{"path": "a.md", "text": "x"}], {"snippet_chars": 200}, ["data"])

    assert result == {"candidates": [{"term": "Invoice"}]}
    assert runner.request == {"documents": [{"path": "a.md", "text": "x"}], "settings": {"snippet_chars": 200}, "keep_surface": ["data"]}
    command, _ = runner.calls[0]
    assert command[:4] == ["uv", "run", "--project", str(tmp_path / "nlp")]
    assert command[command.index("--models-dir") + 1] == str((tmp_path / "models").resolve())


def test_the_tool_runs_without_the_callers_virtual_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/.venv")
    runner = FakeRunner(result={})
    NlpTool(project_dir=tmp_path, models_dir=tmp_path, runner=runner).extract([], {}, [])

    _, kwargs = runner.calls[0]
    assert "VIRTUAL_ENV" not in kwargs["env"]


def test_a_failing_tool_raises_with_its_message(tmp_path):
    runner = FakeRunner(returncode=2, stderr="deriva-nlp: Translation model translate-de_en-1_3 is missing")
    tool = NlpTool(project_dir=tmp_path, models_dir=tmp_path, runner=runner)

    with pytest.raises(NlpToolError, match="translate-de_en-1_3 is missing"):
        tool.extract([], {}, [])


def test_ensure_models_runs_the_models_command(tmp_path):
    runner = FakeRunner()
    NlpTool(project_dir=tmp_path, models_dir=tmp_path / "models", runner=runner).ensure_models()

    command, _ = runner.calls[0]
    assert "models" in command and command[command.index("--models-dir") + 1] == str((tmp_path / "models").resolve())


def test_paths_default_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DERIVA_NLP_PROJECT", str(tmp_path / "p"))
    monkeypatch.setenv("DERIVA_NLP_MODELS_DIR", str(tmp_path / "m"))

    tool = NlpTool()

    assert (tool.project_dir, tool.models_dir) == (tmp_path / "p", tmp_path / "m")


@pytest.mark.integration
def test_the_real_tool_extracts_english_forms():
    """Runs tools/nlp for real (needs `uv` and the models in workspace/cache/nlp)."""
    result = NlpTool().extract([{"path": "a.md", "text": "Der Kunde bezahlt die Rechnung. The clerk approves the invoice."}], {}, [])

    terms = {(c["language"], c["term"]): c["english"] for c in result["candidates"]}
    assert terms[("en", "Invoice")] == "invoice"
    assert result["tool"]["deriva-nlp"]
