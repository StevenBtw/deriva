"""Artifact: one artifact per deployable (unit, library, static bundle), from structure (no LLM, no rule-based relationships)."""

from __future__ import annotations

import json

from deriva.modules.derivation.artifact import ArtifactDerivation
from deriva.services.derivation import DERIVATION_REGISTRY, _role_config

PARAMS = {
    "roles": {
        "names": {"artifact": "Artifact"},
        "element_per": "candidate",
        "name_template": "{container} {role}",
        "container_type": "ApplicationComponent",
        "structural": [{"property": "id", "pattern": ".+", "role": "artifact"}],
        "documentation": "Deployable artifact of {container}.",
    }
}


def test_the_step_is_registered_and_relates_only_through_structure():
    assert DERIVATION_REGISTRY["Artifact"] is ArtifactDerivation
    assert ArtifactDerivation.ELEMENT_TYPE == "Artifact"
    assert ArtifactDerivation.OUTBOUND_RULES == [] and ArtifactDerivation.INBOUND_RULES == []


def test_every_candidate_gets_its_artifact_from_structure_named_after_its_component():
    roles = _role_config(json.dumps(PARAMS))

    assert roles is not None and not roles.labels and not roles.instruction  # no classification call
    assert roles.structural == (("id", ".+", "artifact"),)
    assert roles.name_template == "{container} {role}" and roles.container_type == "ApplicationComponent"
