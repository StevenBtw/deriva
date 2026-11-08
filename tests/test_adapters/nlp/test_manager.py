"""The NLP adapter: candidate terms extracted in-process; translation models downloaded into the models directory."""

from __future__ import annotations

import subprocess
import sys

import pytest

from deriva.adapters.nlp import NlpTool, manager, translate


def test_ensure_models_downloads_into_the_models_directory(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "ensure_spacy", lambda models_dir, download: calls.append(("spacy", models_dir, download)) or {})
    monkeypatch.setattr(manager, "ensure_all", lambda models_dir, download: calls.append(("translation", models_dir, download)) or {})

    NlpTool(models_dir=tmp_path / "models").ensure_models()

    assert calls == [("spacy", tmp_path / "models", True), ("translation", tmp_path / "models", True)]


def test_the_models_directory_comes_from_the_settings(tmp_path, monkeypatch):
    """The tool reads DERIVA_NLP_MODELS_DIR from the merged environment (home .env under the process environment)."""
    monkeypatch.delenv("DERIVA_NLP_MODELS_DIR", raising=False)
    monkeypatch.setattr("deriva.common.settings.read_env_file", lambda: {"DERIVA_NLP_MODELS_DIR": str(tmp_path / "env")})

    assert NlpTool().models_dir == tmp_path / "env"


def test_the_models_directory_defaults_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DERIVA_NLP_MODELS_DIR", str(tmp_path / "m"))

    assert NlpTool().models_dir == tmp_path / "m"


def test_unknown_settings_are_refused_before_anything_loads(tmp_path):
    with pytest.raises(ValueError, match="Unknown settings: snippet_length"):
        NlpTool(models_dir=tmp_path).extract([], {"snippet_length": 200}, [])


@pytest.fixture
def spacy_models(pipelines, nlp_models_dir):
    """The models directory holding the pinned spaCy pipelines, through the shared ``pipelines`` fixture (which downloads
    them on a first run): the test runs in a fresh clone and in CI whatever the order, never skipped."""
    return nlp_models_dir


def test_extract_runs_in_process_with_the_given_settings(spacy_models, monkeypatch):
    """English needs no translation model, so this runs on the spaCy pipelines alone."""
    monkeypatch.setattr(translate, "load_translators", lambda models_dir: {})
    documents = [{"path": "a.md", "text": "The clerk approves the invoice. Customers pay every invoice on time."}]

    result = NlpTool(models_dir=spacy_models).extract(documents, {"snippet_chars": 80}, ["data"])

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


def test_spacy_and_translation_models_of_one_language_are_both_reported(tmp_path, monkeypatch):
    spacy = {"de": tmp_path / "de_core_news_sm", "en": tmp_path / "en_core_web_sm"}
    translation = {"de": tmp_path / "opus-mt-de-en"}
    monkeypatch.setattr(manager, "ensure_spacy", lambda models_dir, download: spacy)
    monkeypatch.setattr(manager, "ensure_all", lambda models_dir, download: translation)

    models = NlpTool(models_dir=tmp_path).ensure_models()

    assert sorted(models) == ["de_core_news_sm", "en_core_web_sm", "opus-mt-de-en"]
