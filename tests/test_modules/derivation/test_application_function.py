"""ApplicationFunction: one function per application component, from structure (no LLM, no rule-based relationships)."""

from __future__ import annotations

import json

from deriva.modules.derivation.application_function import ApplicationFunctionDerivation
from deriva.services.derivation import DERIVATION_REGISTRY, _role_config

PARAMS = {
    "roles": {
        "names": {"behaviour": "Behaviour"},
        "element_per": "candidate",
        "name_template": "{container} {role}",
        "container_type": "ApplicationComponent",
        "structural": [{"property": "id", "pattern": ".+", "role": "behaviour"}],
        "documentation": "Main behaviour of {container}.",
    }
}


def test_the_step_is_registered_and_relates_only_through_structure():
    assert DERIVATION_REGISTRY["ApplicationFunction"] is ApplicationFunctionDerivation
    assert ApplicationFunctionDerivation.OUTBOUND_RULES == [] and ApplicationFunctionDerivation.INBOUND_RULES == []


def test_every_candidate_gets_its_function_from_structure_named_after_its_component():
    roles = _role_config(json.dumps(PARAMS))

    assert roles is not None and not roles.labels and not roles.instruction  # no classification call
    assert roles.structural == (("id", ".+", "behaviour"),)
    assert roles.name_template == "{container} {role}" and roles.container_type == "ApplicationComponent"
