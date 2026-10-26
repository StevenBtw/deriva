"""The shipped file types exclude the documents that describe a reference model, so a fresh install reads the same
input as the benchmark did: each such rule excludes its document wherever the repository sits, also for the B1
baseline, which classifies repository-relative paths."""

from __future__ import annotations

import json
from pathlib import Path

from deriva.modules.extraction.classification import classify_files

SEED = Path(__file__).resolve().parents[3] / "deriva/adapters/database/data/file_types.json"


def test_every_reference_model_rule_of_the_seed_excludes_its_document():
    registry = json.loads(SEED.read_text(encoding="utf-8"))
    rules = [r for r in registry if r["subtype"] == "reference-model"]

    assert rules, "the seed carries the reference-model exclusions"
    for rule in rules:
        assert rule["extension"].startswith("path:**/") and rule["file_type"] == "exclude"
        document = rule["extension"].removeprefix("path:**/")
        for path in (f"repo/{document}", document):
            (classified,) = classify_files([path], registry)["classified"]
            assert (classified["file_type"], classified["subtype"]) == ("exclude", "reference-model"), path
