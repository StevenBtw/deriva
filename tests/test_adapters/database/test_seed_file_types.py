"""The shipped file types name no repository's documents: an exclusion of a reference model's own description belongs
in the user's database (``deriva-cli config filetype add``), where every benchmark session records it in its
``session_inputs.json``."""

from __future__ import annotations

import json
from pathlib import Path

SEED = Path(__file__).resolve().parents[3] / "deriva/adapters/database/data/file_types.json"


def test_the_seed_ships_no_reference_model_exclusions():
    registry = json.loads(SEED.read_text(encoding="utf-8"))

    assert [r["extension"] for r in registry if r["subtype"] == "reference-model"] == []
