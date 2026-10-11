"""The ArchiMate layer of an element type."""

from __future__ import annotations

from deriva.adapters.archimate.models import APPLICATION_LAYER, BUSINESS_LAYER, TECHNOLOGY_LAYER, layer_of


def test_layer_of_each_layer_and_unknown_types():
    assert {layer_of(t) for t in BUSINESS_LAYER} == {"Business"}
    assert {layer_of(t) for t in APPLICATION_LAYER} == {"Application"}
    assert {layer_of(t) for t in TECHNOLOGY_LAYER} == {"Technology"}
    assert layer_of("Junction") == "Other"
