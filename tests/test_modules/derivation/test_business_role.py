"""BusinessRole: a role node of kind "role" becomes a business role, from structure (no LLM, no rule-based relationships);
kind "actor" stays a business actor."""

from __future__ import annotations

import json

from deriva.modules.derivation.business_role import BusinessRoleDerivation
from deriva.services.derivation import DERIVATION_REGISTRY, _role_config

PARAMS = {
    "roles": {
        "names": {"role": "Role"},
        "element_per": "candidate",
        "structural": [{"property": "kind", "pattern": "role", "role": "role"}],
        "structural_as_written": True,
        "documentation": "Business role {members}.",
    }
}


def test_the_step_is_registered_and_relates_only_through_structure():
    assert DERIVATION_REGISTRY["BusinessRole"] is BusinessRoleDerivation
    assert BusinessRoleDerivation.ELEMENT_TYPE == "BusinessRole"
    assert BusinessRoleDerivation.OUTBOUND_RULES == [] and BusinessRoleDerivation.INBOUND_RULES == []


def test_a_role_node_of_kind_role_is_a_business_role_named_as_written_without_a_classification_call():
    roles = _role_config(json.dumps(PARAMS))

    assert roles is not None and not roles.labels and not roles.instruction
    assert roles.structural == (("kind", "role", "role"),)
