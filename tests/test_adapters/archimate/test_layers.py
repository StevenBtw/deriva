"""The ArchiMate layer of an element type."""

from __future__ import annotations

import pytest

from deriva.adapters.archimate.models import APPLICATION_LAYER, BUSINESS_LAYER, TECHNOLOGY_LAYER, layer_of, types_match


@pytest.mark.parametrize(
    ("derived", "reference"),
    [
        ("BusinessFunction", "BusinessProcess"),
        ("BusinessProcess", "BusinessEvent"),
        ("ApplicationFunction", "ApplicationProcess"),
        ("ApplicationInteraction", "ApplicationFunction"),
        ("TechnologyProcess", "TechnologyFunction"),
        ("ApplicationComponent", "ApplicationComponent"),
    ],
)
def test_internal_behaviour_of_one_layer_matches_across_its_types(derived, reference):
    """Process, function, interaction and event are one kind within a layer when a model is compared with a reference."""
    assert types_match(derived, reference)


@pytest.mark.parametrize(
    ("derived", "reference"),
    [
        ("ApplicationFunction", "BusinessProcess"),  # another layer
        ("ApplicationService", "ApplicationFunction"),  # a service is not internal behaviour
        ("BusinessService", "ApplicationService"),
        ("ApplicationComponent", "ApplicationInterface"),  # structure types stay strict
        ("DataObject", "BusinessObject"),
    ],
)
def test_services_structure_and_other_layers_stay_strict(derived, reference):
    assert not types_match(derived, reference)


def test_layer_of_each_layer_and_unknown_types():
    assert {layer_of(t) for t in BUSINESS_LAYER} == {"Business"}
    assert {layer_of(t) for t in APPLICATION_LAYER} == {"Application"}
    assert {layer_of(t) for t in TECHNOLOGY_LAYER} == {"Technology"}
    assert layer_of("Junction") == "Other"
