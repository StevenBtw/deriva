"""Generated views: the viewpoints per level with a deterministic band layout, and their export."""

from __future__ import annotations

from lxml import etree

from deriva.adapters.archimate.models import Element, Relationship
from deriva.adapters.archimate.views import build_views
from deriva.adapters.archimate.xml_export import ArchiMateXMLExporter

NS = {"a": "http://www.opengroup.org/xsd/archimate/3.0/", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}

BOTH, ENTERPRISE, SOLUTION = ["enterprise", "solution"], ["enterprise"], ["solution"]
ELEMENTS = [
    Element(name="Shop", element_type="ApplicationComponent", identifier="ac_shop", properties={"levels": BOTH}),
    Element(name="Shop REST API", element_type="ApplicationInterface", identifier="ai_shop", properties={"levels": SOLUTION}),
    Element(name="Ordering", element_type="ApplicationService", identifier="as_order", properties={"levels": ENTERPRISE}),
    Element(name="Order Data", element_type="DataObject", identifier="do_order", properties={"levels": SOLUTION}),
    Element(name="Order", element_type="BusinessObject", identifier="bo_order", properties={"levels": ENTERPRISE}),
    Element(name="Docker Compose", element_type="Node", identifier="node_env", properties={"levels": ENTERPRISE}),
    Element(name="Customer", element_type="BusinessActor", identifier="ba_customer", properties={"levels": ENTERPRISE}),
    Element(name="Order Line", element_type="DataObject", identifier="do_detail_line", properties={"level": "detail", "parent": "do_order"}),
]
RELATIONSHIPS = [
    Relationship(source="ac_shop", target="ai_shop", relationship_type="Composition", identifier="r1", properties={"levels": SOLUTION}),
    Relationship(source="ac_shop", target="as_order", relationship_type="Realization", identifier="r2", properties={"levels": ENTERPRISE}),
    Relationship(source="do_order", target="do_detail_line", relationship_type="Composition", identifier="r3", properties={"level": "detail"}),
    Relationship(source="do_order", target="bo_order", relationship_type="Realization", identifier="r4", properties={"levels": [], "cross_level": True}),
]


def _by_name(views):
    return {v.name: v for v in views}


def _nodes(view):
    return {n.element for n in view.nodes}


def test_each_level_has_its_viewpoints_with_the_elements_and_relationships_of_that_level():
    views = _by_name(build_views(ELEMENTS, RELATIONSHIPS))

    assert set(views) == {
        "Layered (enterprise)",
        "Application Cooperation (enterprise)",
        "Information Structure (enterprise)",
        "Implementation and Deployment (enterprise)",
        "Business (enterprise)",
        "Application Structure (solution)",
        "Application Cooperation (solution)",
        "Information Structure (solution)",
        "Implementation and Deployment (solution)",
        "Information Structure (detail)",
    }
    assert _nodes(views["Application Cooperation (enterprise)"]) == {"ac_shop", "as_order"}
    assert _nodes(views["Application Cooperation (solution)"]) == {"ac_shop", "ai_shop"}
    assert _nodes(views["Information Structure (enterprise)"]) == {"bo_order"}
    assert _nodes(views["Information Structure (solution)"]) == {"do_order"}
    assert _nodes(views["Information Structure (detail)"]) == {"do_order", "do_detail_line"}
    assert _nodes(views["Application Structure (solution)"]) == {"ac_shop"}
    assert {c.relationship for c in views["Application Cooperation (solution)"].connections} == {"r1"}
    assert {c.relationship for c in views["Layered (enterprise)"].connections} == {"r2"}
    assert {c.relationship for c in views["Information Structure (detail)"].connections} == {"r3"}
    assert {v.name: v.level for v in views.values()}["Application Structure (solution)"] == "solution"
    assert views["Application Structure (solution)"].viewpoint == "Application Structure" and views["Business (enterprise)"].viewpoint == "Business Process Cooperation"


def test_interface_members_are_shown_with_their_interface_in_a_detail_view():
    """The members of an interface (endpoints, pages) were in no view; the interfaces detail view shows them with their
    interface, and only interfaces (their components' own members are in the deployment detail view)."""
    member = Element(name="OrderResource", element_type="ApplicationInterface", identifier="ai_detail_orders", properties={"level": "detail", "parent": "ai_shop"})
    part = Relationship(source="ai_shop", target="ai_detail_orders", relationship_type="Composition", identifier="r5", properties={"level": "detail"})

    views = _by_name(build_views([*ELEMENTS, member], [*RELATIONSHIPS, part]))

    view = views["Application Interfaces (detail)"]
    assert (view.viewpoint, view.level) == ("Application Cooperation", "detail")
    assert _nodes(view) == {"ai_shop", "ai_detail_orders"}
    assert {c.relationship for c in view.connections} == {"r5"}
    # Without members the view is left out, as every detail view is
    assert "Application Interfaces (detail)" not in _by_name(build_views(ELEMENTS, RELATIONSHIPS))


def test_a_cross_level_link_is_in_no_view_and_detail_elements_only_in_detail_views():
    views = build_views(ELEMENTS, RELATIONSHIPS)

    assert not any(c.relationship == "r4" for v in views for c in v.connections)
    assert all("do_detail_line" not in _nodes(v) for v in views if v.level != "detail")


def test_the_layout_puts_layers_in_bands_and_is_the_same_for_any_input_order():
    first = _by_name(build_views(ELEMENTS, RELATIONSHIPS))["Layered (enterprise)"]
    second = _by_name(build_views(list(reversed(ELEMENTS)), list(reversed(RELATIONSHIPS))))["Layered (enterprise)"]

    assert [(n.element, n.x, n.y) for n in first.nodes] == [(n.element, n.x, n.y) for n in second.nodes]
    y = {n.element: n.y for n in first.nodes}
    assert y["ba_customer"] < y["ac_shop"] < y["node_env"]  # business above application above technology


def test_the_export_writes_the_level_property_and_the_views(tmp_path):
    out = tmp_path / "model.xml"
    views = build_views(ELEMENTS, RELATIONSHIPS)
    ArchiMateXMLExporter().export(ELEMENTS, RELATIONSHIPS, str(out), properties={e.identifier: {"level": e.properties.get("level", "architect")} for e in ELEMENTS}, views=views)

    root = etree.parse(str(out)).getroot()
    definitions = root.findall("a:propertyDefinitions/a:propertyDefinition", NS)
    assert [d.findtext("a:name", namespaces=NS) for d in definitions] == ["level"]
    line = root.find("a:elements/a:element[@identifier='do_detail_line']", NS)
    assert line is not None
    assert line.findtext("a:properties/a:property/a:value", namespaces=NS) == "detail"
    diagrams = root.findall("a:views/a:diagrams/a:view", NS)
    assert len(diagrams) == len(views)
    # Each view carries its level, as elements and relationships do
    levels = {d.findtext("a:name", namespaces=NS): d.findtext("a:properties/a:property/a:value", namespaces=NS) for d in diagrams}
    assert levels["Application Structure (solution)"] == "solution" and levels["Layered (enterprise)"] == "enterprise"
    ids = {e.identifier for e in ELEMENTS} | {r.identifier for r in RELATIONSHIPS}
    refs = [n.get("elementRef") for n in root.iter(f"{{{NS['a']}}}node")] + [c.get("relationshipRef") for c in root.iter(f"{{{NS['a']}}}connection")]
    assert refs and set(refs) <= ids
    # The element order of the exchange format: elements, relationships, propertyDefinitions, views
    order = [etree.QName(child).localname for child in root]
    assert order.index("elements") < order.index("relationships") < order.index("propertyDefinitions") < order.index("views")


def test_a_view_needs_its_own_elements():
    """No Business view of application services alone, and no detail view without detail elements."""
    architect_only = [e for e in ELEMENTS if e.element_type != "BusinessActor" and (e.properties or {}).get("level") != "detail"]
    names = {v.name for v in build_views(architect_only, [])}

    assert "Business (enterprise)" not in names
    assert "Information Structure (detail)" not in names and "Information Structure (enterprise)" in names


def test_each_element_type_starts_its_own_row_in_its_band():
    elements = [Element(name=f"C{i}", element_type="ApplicationComponent", identifier=f"ac_{i}") for i in range(2)]
    elements.append(Element(name="Api", element_type="ApplicationInterface", identifier="ai_api"))
    y = {n.element: n.y for n in build_views(elements, [])[0].nodes}

    assert y["ac_0"] == y["ac_1"] < y["ai_api"]


def test_relationships_carry_their_level_property(tmp_path):
    """Relationships take exported properties too, declared with the element ones, after name and documentation."""
    out = tmp_path / "model.xml"
    ArchiMateXMLExporter().export(
        ELEMENTS,
        RELATIONSHIPS,
        str(out),
        properties={e.identifier: {"level": e.properties.get("level", "enterprise")} for e in ELEMENTS},
        relationship_properties={RELATIONSHIPS[0].identifier: {"level": "cross-level"}},
    )

    root = etree.parse(str(out)).getroot()
    assert [d.findtext("a:name", namespaces=NS) for d in root.findall("a:propertyDefinitions/a:propertyDefinition", NS)] == ["level"]
    rel = root.find(f"a:relationships/a:relationship[@identifier='{RELATIONSHIPS[0].identifier}']", NS)
    assert rel is not None
    assert rel.findtext("a:properties/a:property/a:value", namespaces=NS) == "cross-level"
    assert [etree.QName(child).localname for child in rel][-1] == "properties"
