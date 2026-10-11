"""Ontology views over the API."""

from __future__ import annotations

from tests.test_studio.conftest import FakeSession


def test_both_ontologies_are_served(make_client):
    client = make_client(FakeSession(intermediate_ontology={"node_types": [{"name": "Directory"}]}, output_ontology={"element_types": [{"name": "Node"}]}))

    assert client.get("/api/ontology/intermediate").json() == {"node_types": [{"name": "Directory"}]}
    assert client.get("/api/ontology/output").json() == {"element_types": [{"name": "Node"}]}
