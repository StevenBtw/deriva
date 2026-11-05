"""Every ArchiMate 3.2 core type the adapter knows has a wired step. The experimental ones are off by default, keep or
reject broad graph candidates with one closed LLM call per batch, take their names from the candidates, and relate
only through the direct relationships of the metamodel."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deriva.adapters.archimate.models import ELEMENT_TYPES, relationship_tier
from deriva.modules.derivation.core_type import CoreTypeDerivation
from deriva.services.derivation import DERIVATION_REGISTRY, EXPERIMENTAL_TYPES, _role_config

SEED = Path(__file__).parents[3] / "deriva" / "adapters" / "database" / "data" / "derivation_config.json"


def _seed_rows() -> dict[str, dict]:
    data = json.loads(SEED.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else data.get("rows") or data.get("data") or []
    return {r["step_name"]: r for r in rows if r.get("is_active")}


def test_every_core_type_has_a_step():
    assert set(ELEMENT_TYPES) <= set(DERIVATION_REGISTRY)


def test_the_experimental_types_are_exactly_the_types_without_a_step_of_their_own():
    own = {t for t, cls in DERIVATION_REGISTRY.items() if not issubclass(cls, CoreTypeDerivation)}
    assert set(EXPERIMENTAL_TYPES) == set(ELEMENT_TYPES) - own
    for element_type in EXPERIMENTAL_TYPES:
        cls = DERIVATION_REGISTRY[element_type]
        assert issubclass(cls, CoreTypeDerivation) and cls.ELEMENT_TYPE == element_type


@pytest.mark.parametrize("element_type", EXPERIMENTAL_TYPES)
def test_its_relationships_are_direct_ones_of_the_metamodel_to_types_with_a_step(element_type):
    cls = DERIVATION_REGISTRY[element_type]
    assert cls.OUTBOUND_RULES or cls.INBOUND_RULES
    for rule in cls.OUTBOUND_RULES:
        assert relationship_tier(element_type, rule.rel_type, rule.target_type) == "direct", rule
        assert rule.target_type in DERIVATION_REGISTRY and rule.rel_type not in ("Association", "Specialization")
    for rule in cls.INBOUND_RULES:
        assert relationship_tier(rule.target_type, rule.rel_type, element_type) == "direct", rule
        assert rule.target_type in DERIVATION_REGISTRY and rule.rel_type not in ("Association", "Specialization")


@pytest.mark.parametrize("element_type", EXPERIMENTAL_TYPES)
def test_its_shipped_step_is_off_and_classifies_with_one_closed_llm_call(element_type):
    row = _seed_rows().get(element_type)
    assert row is not None, f"no shipped config row for {element_type}"
    assert row["enabled"] is False and row["llm"] is True and row["phase"] == "generate"
    assert row["temperature"] == 0.0  # like the other generate steps, not the LLM_TEMPERATURE fallback
    # The fields the derivation service requires of a generate step, or it fails at run time
    assert row["instruction"] and row["input_graph_query"] and row["example"] and row["max_candidates"] > 0 and row["batch_size"] > 0
    roles = _role_config(row["params"])
    assert roles is not None and roles.labels and roles.instruction
    assert len(roles.names) == 1 and roles.element_per == "candidate" and not roles.naming_call and not roles.structural


def test_an_experimental_step_runs_on_an_empty_graph_without_a_call():
    from deriva.modules.derivation.base import ElementPrompt, GenerationResult

    graph = MagicMock()
    graph.query.return_value = []
    llm = MagicMock()
    for element_type in EXPERIMENTAL_TYPES:
        result = DERIVATION_REGISTRY[element_type]().generate(
            graph_manager=graph,
            archimate_manager=MagicMock(),
            llm_query_fn=llm,
            query="MATCH (n) RETURN n",
            instruction="",
            example="",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
            prompt=ElementPrompt(persona="Derive elements.", candidates="Candidates.", rules="{abstention}Rules.", abstention=""),
            roles=_role_config(json.dumps({"roles": {"labels": ["BusinessConcept"], "instruction": "Keep or none.", "names": {"keep": element_type}, "element_per": "candidate"}})),
        )
        assert isinstance(result, GenerationResult) and result.success and result.elements_created == 0
    llm.assert_not_called()
