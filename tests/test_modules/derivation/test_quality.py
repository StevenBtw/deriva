"""Model quality: a verdict on a derived model from its structure (a report; it changes no result)."""

from __future__ import annotations

from deriva.modules.derivation.quality import model_quality

THRESHOLDS = {"quality_max_orphan_share": 0.25, "quality_max_structural_share": 0.8}


def _element(identifier: str, layer: str = "Application", sources: list[str] | None = None, element_type: str = "ApplicationComponent") -> dict:
    return {"id": identifier, "name": identifier.title(), "type": element_type, "layer": layer, "sources": sources or []}


def _rel(source: str, target: str, relationship_type: str = "Serving") -> dict:
    return {"source": source, "target": target, "type": relationship_type}


def _quality(elements, relationships, located=None, artifacts=frozenset(), source_files=()):
    return model_quality(elements, relationships, located or {}, set(artifacts), list(source_files), THRESHOLDS)


def test_a_connected_model_on_both_layers_is_ok():
    elements = [_element("app"), _element("api", element_type="ApplicationInterface"), _element("db", layer="Technology", element_type="SystemSoftware")]
    report = _quality(elements, [_rel("api", "app"), _rel("db", "app"), _rel("app", "api", "Composition")])

    assert report["verdict"] == "ok" and report["reasons"] == []
    assert (report["elements"], report["relationships"], report["orphans"]) == (3, 3, [])
    assert report["layers"] == {"Business": 0, "Application": 2, "Technology": 1}
    assert report["relationship_types"] == {"Serving": 2, "Composition": 1}


def test_many_orphans_and_containment_only_make_it_weak():
    """The shape seen on a repository whose code was not read: loose elements held together by Composition only."""
    elements = [_element(f"c{i}") for i in range(6)] + [_element("db", layer="Technology", element_type="SystemSoftware")]
    report = _quality(elements, [_rel("c0", "c1", "Composition"), _rel("c0", "c2", "Composition"), _rel("c0", "db", "Aggregation")])

    assert report["verdict"] == "weak"
    assert report["reasons"] == [
        "3 of 7 elements (43%) have no relationship (above 25%)",
        "all 3 relationships are Composition or Aggregation (above 80%)",
    ]
    assert [o["id"] for o in report["orphans"]] == ["c3", "c4", "c5"]


def test_an_empty_application_or_technology_layer_makes_it_weak_but_an_empty_business_layer_does_not():
    report = _quality([_element("app"), _element("api", element_type="ApplicationInterface")], [_rel("api", "app")])

    assert report["reasons"] == ["no Technology element"]
    assert report["layers"]["Business"] == 0


def test_an_element_whose_sources_hold_no_artifact_is_flagged():
    """A folder-like source counts when a source file lies under it; a file, type or method is evidence itself."""
    elements = [
        _element("inbound", sources=["dir::in"]),
        _element("orders", sources=["unit::orders"]),
        _element("webui", sources=["file::index"], element_type="ApplicationInterface"),
        _element("data", sources=["domain::orders"], element_type="DataObject"),
        _element("db", layer="Technology", sources=["software::db"], element_type="SystemSoftware"),
    ]
    rels = [_rel("webui", "orders"), _rel("inbound", "orders"), _rel("orders", "data", "Access"), _rel("db", "orders")]
    located = {"dir::in": "repo/In", "unit::orders": "repo/orders", "file::index": "repo/web/index.html"}
    report = _quality(elements, rels, located, artifacts={"file::index"}, source_files=["repo/orders/Order.java", "repo/Inbound.java"])

    assert report["unsupported"] == [{"id": "inbound", "name": "Inbound", "type": "ApplicationComponent", "sources": ["repo/In"]}]
    assert report["verdict"] == "weak"
    assert report["reasons"] == ["1 element has no file, type or method behind its sources (Inbound)"]


def test_an_empty_model_is_weak_with_one_reason():
    report = _quality([], [])

    assert report["verdict"] == "weak" and report["reasons"] == ["the model has no elements"]
