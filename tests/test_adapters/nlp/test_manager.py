"""The NLP adapter: candidate terms extracted in-process; translation models downloaded into the models directory."""

from __future__ import annotations

import subprocess
import sys

import pytest

from deriva.adapters.nlp import NlpTool, manager, translate


def test_ensure_models_downloads_into_the_models_directory(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "ensure_all", lambda models_dir, download: calls.append((models_dir, download)))

    NlpTool(models_dir=tmp_path / "models").ensure_models()

    assert calls == [(tmp_path / "models", True)]


def test_the_models_directory_defaults_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DERIVA_NLP_MODELS_DIR", str(tmp_path / "m"))

    assert NlpTool().models_dir == tmp_path / "m"


def test_unknown_settings_are_refused_before_anything_loads(tmp_path):
    with pytest.raises(ValueError, match="Unknown settings: snippet_length"):
        NlpTool(models_dir=tmp_path).extract([], {"snippet_length": 200}, [])


def test_extract_runs_in_process_with_the_given_settings(tmp_path, monkeypatch):
    """English needs no translation model, so this runs on the spaCy pipelines alone."""
    monkeypatch.setattr(translate, "load_translators", lambda models_dir: {})
    documents = [{"path": "a.md", "text": "The clerk approves the invoice. Customers pay every invoice on time."}]

    result = NlpTool(models_dir=tmp_path).extract(documents, {"snippet_chars": 80}, ["data"])

    assert result["settings"]["snippet_chars"] == 80
    english = {(c["language"], c["term"]): c["english"] for c in result["candidates"]}
    assert english.get(("en", "Invoice")) == "invoice", english  # a failure shows what the pinned models produced
    assert result["tool"]["spacy"]


def test_importing_the_adapter_does_not_load_spacy():
    """The CLI imports the adapter on every command; spaCy and CTranslate2 load on the first extraction."""
    code = "import sys, deriva.adapters.nlp; print(sorted(m for m in ('spacy', 'ctranslate2') if m in sys.modules))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip() == "[]"


@pytest.mark.integration
def test_the_real_models_give_english_forms():
    """Needs the translation models in workspace/cache/nlp. The language is detected per document."""
    documents = [{"path": "de.md", "text": "Der Kunde bezahlt die Rechnung."}, {"path": "en.md", "text": "The clerk approves the invoice."}]

    result = NlpTool().extract(documents, {}, [])

    terms = {(c["language"], c["term"]): c["english"] for c in result["candidates"]}
    assert terms[("en", "Invoice")] == "invoice"
    assert terms[("de", "Rechnung")] == "invoice"
