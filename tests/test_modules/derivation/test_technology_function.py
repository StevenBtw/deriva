"""TechnologyFunction and TechnologyService: one function and one service per realizer (the platform node, a service
in the environment), from structure (no LLM, no rule-based relationships)."""

from __future__ import annotations

import json

from deriva.modules.derivation.technology_function import TechnologyFunctionDerivation
from deriva.modules.derivation.technology_service import TechnologyServiceDerivation
from deriva.services.derivation import DERIVATION_REGISTRY, _role_config


def test_both_steps_are_registered_and_relate_only_through_structure():
    assert DERIVATION_REGISTRY["TechnologyFunction"] is TechnologyFunctionDerivation
    assert TechnologyFunctionDerivation.ELEMENT_TYPE == "TechnologyFunction"
    for step in (TechnologyFunctionDerivation, TechnologyServiceDerivation):
        assert step.OUTBOUND_RULES == [] and step.INBOUND_RULES == []


def test_a_realizer_gets_its_behaviour_and_its_service_named_by_kind_without_a_call():
    function = _role_config(
        json.dumps(
            {
                "roles": {
                    "names": {"behaviour": "Behaviour"},
                    "element_per": "candidate",
                    "name_template": "{subject} {role}",
                    "structural": [{"property": "kind", "pattern": "database|cache", "role": "behaviour"}],
                }
            }
        )
    )
    service = _role_config(
        json.dumps(
            {
                "roles": {
                    "names": {"database": "Relational Database"},
                    "element_per": "candidate",
                    "name_template": "{role}",
                    "structural": [{"property": "kind", "pattern": "database", "role": "database"}],
                }
            }
        )
    )

    assert function is not None and not function.labels and function.name_template == "{subject} {role}"
    assert service is not None and not service.labels and service.structural == (("kind", "database", "database"),)
