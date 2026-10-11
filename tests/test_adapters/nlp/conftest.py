"""Shared fixtures. The spaCy pipelines download into DERIVA_NLP_MODELS_DIR (default: the repository's
workspace/cache/nlp) on first use; tests that use the translation packages are `integration` tests and need them there."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

MODELS_DIR = Path(os.environ.get("DERIVA_NLP_MODELS_DIR", Path(__file__).resolve().parents[3] / "workspace" / "cache" / "nlp"))


@pytest.fixture(scope="session")
def pipelines():
    from deriva.adapters.nlp.phrases import load_pipelines

    return load_pipelines(MODELS_DIR)


@pytest.fixture(scope="session")
def translators():
    from deriva.adapters.nlp.translate import load_translators

    return load_translators(MODELS_DIR)
