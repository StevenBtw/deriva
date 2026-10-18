"""Reading an exported model per level: the level property is a set ("enterprise solution"); "architect" is every
derived element (any level but detail), as earlier exports wrote it."""

from __future__ import annotations

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter
from deriva.modules.analysis.semantic_matching import parse_exchange_format_xml

ELEMENTS = [
    Element(name="Shop", element_type="ApplicationComponent", identifier="ac_sys"),
    Element(name="Orders", element_type="ApplicationComponent", identifier="ac_orders"),
    Element(name="Api", element_type="ApplicationInterface", identifier="ai_orders"),
    Element(name="Order Line", element_type="DataObject", identifier="do_line"),
    Element(name="Legacy", element_type="BusinessObject", identifier="bo_legacy"),
]
LEVELS = {"ac_sys": "enterprise", "ac_orders": "enterprise solution", "ai_orders": "solution", "do_line": "detail", "bo_legacy": "architect"}


def _export(tmp_path):
    path = tmp_path / "model.xml"
    relationships = [Relationship(source="ac_orders", target="ai_orders", relationship_type="Composition", identifier="r1")]
    ArchiMateXMLExporter().export(ELEMENTS, relationships, str(path), properties={i: {"level": v} for i, v in LEVELS.items()})
    return path


def _ids(path, level):
    elements, relationships = parse_exchange_format_xml(path, level=level)
    return sorted(e.identifier for e in elements), [r.identifier for r in relationships]


def test_each_level_reads_its_elements_and_architect_reads_every_derived_one(tmp_path):
    path = _export(tmp_path)

    assert _ids(path, "enterprise")[0] == ["ac_orders", "ac_sys", "bo_legacy"]  # an earlier export's architect is enterprise
    assert _ids(path, "solution") == (["ac_orders", "ai_orders"], ["r1"])
    assert _ids(path, "architect")[0] == ["ac_orders", "ac_sys", "ai_orders", "bo_legacy"]  # all but detail
    assert _ids(path, "detail")[0] == ["do_line"]
    assert len(_ids(path, None)[0]) == 5
