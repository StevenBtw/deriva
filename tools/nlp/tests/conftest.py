"""Shared fixtures. Tests marked `models` need the spaCy models (dependencies) and the translation
packages in DERIVA_NLP_MODELS_DIR (default: the repository's workspace/cache/nlp)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

MODELS_DIR = Path(os.environ.get("DERIVA_NLP_MODELS_DIR", Path(__file__).resolve().parents[3] / "workspace" / "cache" / "nlp"))


@pytest.fixture(scope="session")
def pipelines():
    from deriva_nlp.phrases import load_pipelines

    return load_pipelines()


@pytest.fixture(scope="session")
def translators():
    from deriva_nlp.translate import load_translators

    return load_translators(MODELS_DIR)
