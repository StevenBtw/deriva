"""Generated views (pure): ArchiMate viewpoints per level with a deterministic band layout.

Each viewpoint (ArchiMate 3.2 Specification, chapter 13) shows the architect elements of its types; a detail
variant adds the detail elements (property ``level`` = detail) nested under those types. The layout puts the
layers in horizontal bands (business, application, technology) and the elements of a band in a grid, ordered by
type and name, each detail element right after its parent, so the same model gives the same view in every run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Element, Relationship, layer_of

# (view name, viewpoint, element types, with detail elements)
VIEWPOINTS: tuple[tuple[str, str, frozenset[str] | None, bool], ...] = (
    ("Layered", "Layered", None, False),
    ("Application Cooperation", "Application Cooperation", frozenset({"ApplicationComponent", "ApplicationInterface", "ApplicationService"}), False),
    ("Information Structure", "Information Structure", frozenset({"BusinessObject", "DataObject"}), False),
    ("Information Structure (detail)", "Information Structure", frozenset({"BusinessObject", "DataObject"}), True),
    ("Implementation and Deployment", "Implementation and Deployment", frozenset({"ApplicationComponent", "Node", "Device", "SystemSoftware", "TechnologyService"}), False),
    (
        "Implementation and Deployment (detail)",
        "Implementation and Deployment",
        frozenset({"ApplicationComponent", "Node", "Device", "SystemSoftware", "TechnologyService", "Artifact"}),
        True,
    ),
    ("Business", "Business Process Cooperation", frozenset({"BusinessActor", "BusinessProcess", "BusinessFunction", "BusinessEvent", "ApplicationService"}), False),
)
# A view needs an element of its anchor types (the Business view: a business element, not application services alone)
ANCHORS = {"Business": frozenset({"BusinessActor", "BusinessProcess", "BusinessFunction", "BusinessEvent"})}
BANDS = ("Business", "Application", "Technology", "Other")
TYPE_ORDER = (
    "BusinessActor", "BusinessFunction", "BusinessProcess", "BusinessEvent", "BusinessObject",
    "ApplicationComponent", "ApplicationInterface", "ApplicationService", "DataObject",
    "Node", "Device", "SystemSoftware", "TechnologyService", "Artifact",
)  # fmt: skip
COLUMNS, WIDTH, HEIGHT, GAP, BAND_GAP, MARGIN = 6, 160, 60, 20, 60, 20


@dataclass(frozen=True)
class ViewNode:
    identifier: str
    element: str
    x: int
    y: int
    w: int = WIDTH
    h: int = HEIGHT


@dataclass(frozen=True)
class ViewConnection:
    identifier: str
    relationship: str
    source: str  # node identifiers
    target: str


@dataclass
class View:
    identifier: str
    name: str
    viewpoint: str
    level: str = "architect"  # detail: the view shows the detail elements too
    nodes: list[ViewNode] = field(default_factory=list)
    connections: list[ViewConnection] = field(default_factory=list)


def _level(e: Element) -> str:
    return str((e.properties or {}).get("level") or "architect")


def _order(e: Element) -> tuple[int, str, str]:
    return (TYPE_ORDER.index(e.element_type) if e.element_type in TYPE_ORDER else len(TYPE_ORDER), e.name.casefold(), e.identifier)


def _layout(view: View, shown: list[Element]) -> None:
    by_parent: dict[str, list[Element]] = {}
    for e in shown:
        if _level(e) == "detail":
            by_parent.setdefault(str((e.properties or {}).get("parent") or ""), []).append(e)
    shown_ids = {e.identifier for e in shown}
    y = MARGIN
    for band in BANDS:
        # One group per element type (each starts a new row), every element followed by its detail members
        groups: dict[str, list[Element]] = {}
        for e in sorted((e for e in shown if _level(e) != "detail" and layer_of(e.element_type) == band), key=_order):
            groups.setdefault(e.element_type, []).append(e)
            groups[e.element_type] += sorted(by_parent.get(e.identifier, []), key=_order)
        # Detail elements whose parent is not in the view still get a place, after the band's own
        orphans = (e for e in shown if _level(e) == "detail" and layer_of(e.element_type) == band and str((e.properties or {}).get("parent")) not in shown_ids)
        if rest := sorted(orphans, key=_order):
            groups[""] = rest
        if not groups:
            continue
        for group in groups.values():
            for i, e in enumerate(group):
                row, column = divmod(i, COLUMNS)
                node_id = f"{view.identifier}-n-{e.identifier}"
                view.nodes.append(ViewNode(identifier=node_id, element=e.identifier, x=MARGIN + column * (WIDTH + GAP), y=y + row * (HEIGHT + GAP)))
            y += (len(group) + COLUMNS - 1) // COLUMNS * (HEIGHT + GAP)
        y += BAND_GAP


def build_views(elements: list[Element], relationships: list[Relationship]) -> list[View]:
    """The views of the model, one per viewpoint that has elements, in VIEWPOINTS order."""
    views: list[View] = []
    for number, (name, viewpoint, types, with_detail) in enumerate(VIEWPOINTS, 1):
        shown = [e for e in elements if (types is None or e.element_type in types) and (with_detail or _level(e) != "detail")]
        anchors = ANCHORS.get(name)
        if not shown or (anchors and not any(e.element_type in anchors for e in shown)) or (with_detail and not any(_level(e) == "detail" for e in shown)):
            continue
        view = View(identifier=f"view-{number}", name=name, viewpoint=viewpoint, level="detail" if with_detail else "architect")
        _layout(view, shown)
        node_of = {n.element: n.identifier for n in view.nodes}
        for r in sorted(relationships, key=lambda r: r.identifier):
            if r.source in node_of and r.target in node_of:
                connection = ViewConnection(identifier=f"{view.identifier}-c-{r.identifier}", relationship=r.identifier, source=node_of[r.source], target=node_of[r.target])
                view.connections.append(connection)
        views.append(view)
    return views
