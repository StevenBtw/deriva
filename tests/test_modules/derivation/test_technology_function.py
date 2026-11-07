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


def test_subject_as_written_names_graph_labels_and_needs_a_subject_in_the_template():
    import pytest

    base = {
        "names": {"behaviour": "Behaviour"},
        "element_per": "candidate",
        "name_template": "{subject} {role}",
        "structural": [{"property": "kind", "pattern": "database", "role": "behaviour"}],
    }

    config = _role_config(json.dumps({"roles": {**base, "subject_as_written": ["Software"]}}))

    assert config is not None and config.subject_as_written == frozenset({"Software"})
    for wrong in ({**base, "subject_as_written": "Software"}, {**base, "subject_as_written": [""]}, {**base, "name_template": "{role}", "subject_as_written": ["Software"]}):
        with pytest.raises(ValueError, match="subject_as_written"):
            _role_config(json.dumps({"roles": wrong}))


def test_repeat_template_needs_a_template_per_candidate():
    import pytest

    base = {
        "names": {"database": "Store and Query Data"},
        "element_per": "candidate",
        "name_template": "{role}",
        "structural": [{"property": "kind", "pattern": "database", "role": "database"}],
    }

    config = _role_config(json.dumps({"roles": {**base, "repeat_template": "{role} ({subject})"}}))

    assert config is not None and config.repeat_template == "{role} ({subject})"
    for wrong in (
        {**base, "repeat_template": 3},
        {**base, "repeat_template": "{role}"},
        {**base, "name_template": "", "repeat_template": "{role} ({subject})"},
        {**base, "repeat_template": "{role} ({subject}, {realizer})"},  # a field no name fills
        {**base, "repeat_template": "{role} ({subject"},  # not well formed (an open brace)
        {**base, "repeat_template": "{role} ({subject.name})"},  # an attribute the name text has not
    ):
        with pytest.raises(ValueError, match="repeat_template"):
            _role_config(json.dumps({"roles": wrong}))


def test_the_shipped_function_config_reads_its_realizer_only_in_the_repeat_template():
    """Functions are named by kind ({role}); the realizer, as written, appears only when two names would repeat. Read
    from the shipped seed row, so the test fails when the seed loses either key."""
    from deriva.adapters.database.manager import SCRIPTS_DIR

    rows = json.loads((SCRIPTS_DIR.parent / "data" / "derivation_config.json").read_text(encoding="utf-8"))
    [row] = [r for r in rows if r["step_name"] == "TechnologyFunction"]
    config = _role_config(row["params"])

    assert config is not None and (config.name_template, config.repeat_template, config.subject_as_written) == ("{role}", "{role} ({subject})", frozenset({"Software"}))
