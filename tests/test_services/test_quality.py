"""The model quality service: reads the model, the graph and the thresholds, writes nothing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.adapters.archimate.models import Element, Relationship


def _graph():
    def query(text, params=None):
        if "n.path IS NOT NULL" in text:
            return [{"id": "dir::in", "p": "repo/In"}, {"id": "unit::orders", "p": "repo/orders"}]
        if "n.filePath IS NOT NULL" in text:
            return [{"id": "file::order", "p": "repo/orders/Order.java", "l": ["Graph", "File"]}]
        if "fileType = 'source'" in text:
            return [{"p": "repo/orders/Order.java"}]
        raise AssertionError(text)

    graph = MagicMock()
    graph.query.side_effect = query
    return graph


def test_the_service_reads_elements_relationships_and_sources_and_the_thresholds():
    from deriva.services.quality import model_quality

    model = MagicMock()
    model.get_elements.return_value = [
        Element(name="Inbound", element_type="ApplicationComponent", identifier="inbound", properties={"source": "dir::in"}),
        Element(name="Orders", element_type="ApplicationComponent", identifier="orders", properties={"sources": ["unit::orders"]}),
        Element(name="Db", element_type="SystemSoftware", identifier="db"),
        Element(name="Old", element_type="ApplicationComponent", identifier="old", enabled=False),
    ]
    model.get_relationships.return_value = [
        Relationship(source="inbound", target="orders", relationship_type="Serving"),
        Relationship(source="db", target="orders", relationship_type="Serving"),
    ]

    with patch("deriva.services.quality.config.get_setting", side_effect=lambda engine, key, default=None: {"quality_max_orphan_share": "0.5"}.get(key)):
        report = model_quality(MagicMock(), _graph(), model)

    assert report["elements"] == 3 and report["layers"] == {"Business": 0, "Application": 2, "Technology": 1}
    assert [u["id"] for u in report["unsupported"]] == ["inbound"]
    assert report["verdict"] == "weak"
    model.add_element.assert_not_called()


def test_thresholds_fall_back_to_their_defaults_when_unset_or_not_a_share():
    from deriva.services import config

    with patch(
        "deriva.services.config.get_setting", side_effect=lambda engine, key, default=None: {"quality_max_orphan_share": "lots", "quality_max_structural_share": "0.9"}.get(key)
    ):
        thresholds = config.get_quality_thresholds(MagicMock())

    assert thresholds == {"quality_max_orphan_share": 0.25, "quality_max_structural_share": 0.9}
